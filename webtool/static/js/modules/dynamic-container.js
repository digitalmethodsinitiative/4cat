export const dynamicContainer = {
    /**
     * Set up updater interval for dynamic containers
     */
    init: function () {
        // Update dynamic containers
        setInterval(dynamicContainer.refresh, 250);
    },

    refresh: function () {
        if (!document.hasFocus()) {
            //don't hammer the server while user is looking at something else
            return;
        }

        $('.content-container').each(function () {
            let url = $(this).attr('data-source');
            if(!url) {
                return;
            }
            let interval = parseInt($(this).attr('data-interval'));
            let previous = $(this).attr('data-last-call');
            if (!previous) {
                previous = 0;
            }

            let now = Math.floor(Date.now() / 1000);
            if ((now - previous) < interval) {
                return;
            }

            let container = $(this);
            container.attr('data-last-call', Math.floor(Date.now() / 1000));
            fetch(url, {
                method: 'GET'
            }).then(async (response) => {
                if (response.ok) {
                    const text = await response.text();
                    if (text === container.html()) {
                        return;
                    }
                    container.html(text);
                }
            });
        });
    }
};

export const module = dynamicContainer;