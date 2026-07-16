# NVIDIA silently re-published nvidia-l4t-3d-core_36.5.0-20260115194252_arm64.deb;
# the SHA the recipe expected no longer matches. The new SHA is
# 910b16711cd14f39699475e42c1e9316ad5a6cf725b9142f5ebb96af7bcf49d7 (89MB),
# observed during a local fetch on 2026-05-16.
MAINSUM = "910b16711cd14f39699475e42c1e9316ad5a6cf725b9142f5ebb96af7bcf49d7"

# The same re-published .deb carries the updated NVIDIA EULA
# (v. February 25, 2025), matching the other nvidia-l4t-3d-core recipes.
L4T_DEB_COPYRIGHT_MD5 = "8c7016b98a9864afb8cc0a7eb8ba62fa"
