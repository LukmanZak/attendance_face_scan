from . import controllers
from . import models


def post_init_hook(env):
    env["hr.employee"].sudo()._rebuild_face_scan_index()
