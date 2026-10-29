"""Employee face embeddings stored and searched by pgvector."""

from odoo import fields, models

from .face_engine import EMBEDDING_DIMENSION, MODEL_VERSION


class AttendanceFaceEmbedding(models.Model):
    _name = "attendance.face.embedding"
    _description = "Attendance Face Embedding"
    _rec_name = "employee_id"
    _order = "employee_id"

    employee_id = fields.Many2one(
        "hr.employee",
        required=True,
        ondelete="cascade",
        index=True,
        groups="hr_attendance.group_hr_attendance_manager",
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        index=True,
        groups="hr_attendance.group_hr_attendance_manager",
    )
    embedding = fields.Text(
        required=True,
        groups="hr_attendance.group_hr_attendance_manager",
    )
    model_version = fields.Char(
        required=True,
        default=MODEL_VERSION,
        groups="hr_attendance.group_hr_attendance_manager",
    )
    source_image_sha256 = fields.Char(
        required=True,
        index=True,
        groups="hr_attendance.group_hr_attendance_manager",
    )
    indexed_at = fields.Datetime(
        required=True,
        default=fields.Datetime.now,
        groups="hr_attendance.group_hr_attendance_manager",
    )

    _employee_unique = models.Constraint(
        "unique(employee_id)",
        "An employee can have only one active face embedding.",
    )

    def init(self):
        self.env.cr.execute("CREATE EXTENSION IF NOT EXISTS vector")
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS attendance_face_embedding_hnsw_idx
            ON attendance_face_embedding
            USING hnsw ((embedding::vector(128)) vector_cosine_ops)
            """
        )

    @staticmethod
    def _vector_literal(vector):
        if len(vector) != EMBEDDING_DIMENSION:
            raise ValueError("Unexpected face embedding dimensions.")
        return "[" + ",".join(f"{float(value):.8f}" for value in vector) + "]"

    def best_matches(self, company, vector, limit=2):
        vector_literal = self._vector_literal(vector)
        self.env.cr.execute(
            """
            SELECT embedding_row.employee_id,
                   1 - (embedding_row.embedding::vector(128) <=> %s::vector(128)) AS similarity,
                   embedding_row.source_image_sha256,
                   embedding_row.model_version
              FROM attendance_face_embedding AS embedding_row
              JOIN hr_employee AS employee
                ON employee.id = embedding_row.employee_id
             WHERE embedding_row.company_id = %s
               AND employee.company_id = %s
               AND employee.active
             ORDER BY embedding_row.embedding::vector(128) <=> %s::vector(128)
             LIMIT %s
            """,
            (vector_literal, company.id, company.id, vector_literal, limit),
        )
        return self.env.cr.fetchall()

    def upsert_employee_embedding(self, employee, vector, image_sha256):
        values = {
            "company_id": employee.company_id.id,
            "embedding": self._vector_literal(vector),
            "model_version": MODEL_VERSION,
            "source_image_sha256": image_sha256,
            "indexed_at": fields.Datetime.now(),
        }
        existing = self.sudo().search([("employee_id", "=", employee.id)], limit=1)
        if existing:
            existing.write(values)
        else:
            self.sudo().create({"employee_id": employee.id, **values})
