async function load() {
    const imported_modules = [
        await import("./modules/util.js"),

        await import("./modules/create-dataset.js"),
        await import("./modules/dataset-page.js"),
        await import("./modules/dynamic-container.js"),
        await import("./modules/multichoice.js"),
        await import("./modules/popup.js"),
        await import("./modules/run-processor.js"),
        await import("./modules/tooltip.js"),
        await import("./modules/ui-helpers.js"),
    ];

    for(const module of imported_modules) {
        if(module.module) {
            module.module.init();
        }
    }
}

$(load());
