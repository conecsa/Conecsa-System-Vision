fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Compile protobuf for the WASM frontend.
    std::fs::create_dir_all("src/proto")?;
    prost_build::Config::new()
        .out_dir("src/proto")
        .compile_protos(&["../proto/detection.proto"], &["../proto"])?;

    // i18n codegen (leptos_i18n) — only meaningful for the wasm frontend build.
    // Catalogs live in the repo-root shared `i18n/` directory; the Docker build
    // copies it next to `system-vision/` so the relative path holds there too.
    if std::env::var("CARGO_CFG_TARGET_ARCH").as_deref() == Ok("wasm32") {
        use leptos_i18n_build::{Config, ParseOptions, TranslationsInfos};

        let out = std::path::PathBuf::from(std::env::var_os("OUT_DIR").unwrap()).join("i18n");
        let cfg = Config::new("en")?
            .add_locales(["pt-BR", "es"])?
            .locales_path("../i18n/system-vision")
            .add_namespaces([
                "common",
                "main",
                "control_panel",
                "stream",
                "models",
                "camera",
                "settings",
                "training",
                "statistics",
                "flow",
            ])?
            .parse_options(ParseOptions::new().interpolate_display(true));
        let infos = TranslationsInfos::parse(cfg)?;
        infos.emit_diagnostics();
        infos.rerun_if_locales_changed();
        infos.generate_i18n_module(out)?;
    }
    Ok(())
}
