# Upstream requires 'pam' when the init manager is systemd (the stock
# weston.service relies on PAMName= for a logind session). This distro has no
# PAM; the weston-init bbappend ships a drop-in that provides XDG_RUNTIME_DIR
# and seat access without it (RuntimeDirectory= + libseat builtin backend), so
# the requirement does not apply.
REQUIRED_DISTRO_FEATURES:remove = "pam"
