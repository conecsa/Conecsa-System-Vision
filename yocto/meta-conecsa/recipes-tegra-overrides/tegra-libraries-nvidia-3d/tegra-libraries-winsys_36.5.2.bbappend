# meta-tegra scarthgap (053a4e97, L4T R36.5.2) pins a MAINSUM for
# tegra-libraries-winsys that does not match the deb NVIDIA actually serves
# (nvidia-l4t-3d-core_36.5.2-20260716114719_arm64.deb). The sibling recipes
# for the same deb (tegra-libraries-glxcore / -glescore) carry the correct
# checksum and copyright md5, verified against the NVIDIA apt index on
# 2026-09-02. Scoped to PV 36.5.2 on purpose: when meta-tegra moves to the
# next L4T release this bbappend stops applying instead of forcing a stale
# checksum onto the new recipe. Delete it once upstream fixes the recipe.
MAINSUM = "78944c0ca8a1f12f5bf890746f3920f7aed6d2e8fa883c996d7e4ebba6901996"
L4T_DEB_COPYRIGHT_MD5 = "8c7016b98a9864afb8cc0a7eb8ba62fa"
