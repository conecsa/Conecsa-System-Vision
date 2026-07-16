# webkitgtk 2.44 enables USE_GBM by default (OptionsGTK.cmake), which needs
# mesa's libgbm at configure time. The recipe never declares it: on plain
# oe-core builds gbm arrives implicitly because virtual/egl is mesa, but on
# tegra virtual/egl is libglvnd, so configure fails with "GBM is required for
# USE_GBM". Depend on it explicitly — at runtime mesa's libgbm dispatches to
# the NVIDIA backend (tegra-libraries-gbm-backend, see
# PREFERRED_RPROVIDER_tegra-gbm-backend in meta-tegra).
DEPENDS += "virtual/libgbm"
