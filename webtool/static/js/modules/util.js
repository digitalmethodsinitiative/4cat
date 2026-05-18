/**
 * Get absolute API URL to call
 *
 * Determines proper URL to call
 *
 * @param endpoint Relative URL to call (/api/endpoint)
 * @returns  Absolute URL
 */
export function getRelativeURL(endpoint) {
    let root = $("body").attr("data-url-root");
    if (!root) {
        root = '/';
    }
    return root + endpoint;
}

export function applyProgress(element, progress) {
    if (element.parent().hasClass('button-like')) {
        element = element.parent();
    }

    let current_progress = Array(...element[0].classList).filter(z => z.indexOf('progress-') === 0);
    for (let class_name in current_progress) {
        class_name = current_progress[class_name];
        element.removeClass(class_name);
    }

    if (progress && progress > 0 && progress < 100) {
        element.addClass('progress-' + progress);
        if (!element.hasClass('progress')) {
            element.addClass('progress');
        }
    }
}

export async function fetch_with_progress(url, callback = null) {
    // Step 1: start the fetch and obtain a reader
    let response = await fetch(url);
    const reader = response.body.getReader();

    // Step 2: get total length
    const contentLength = +response.headers.get('Content-Length');

    // Step 3: read the data
    let receivedLength = 0; // received that many bytes at the moment
    let chunks = []; // array of received binary chunks (comprises the body)
    while (true) {
        const {done, value} = await reader.read();

        if (done) {
            break;
        }

        chunks.push(value);
        receivedLength += value.length;

        if(callback) {
            callback(receivedLength, contentLength);
        }
    }

    // Step 4: concatenate chunks into single Uint8Array
    let chunksAll = new Uint8Array(receivedLength); // (4.1)
    let position = 0;
    for (let chunk of chunks) {
        chunksAll.set(chunk, position); // (4.2)
        position += chunk.length;
    }

    // Step 5: decode into a string
    return new TextDecoder("utf-8").decode(chunksAll);
}

/**
 * Return a FileReader, but as a Promise that can be awaited
 *
 * @param file
 * @returns {Promise<unknown>}
 * @constructor
 */
export function FileReaderPromise(file) {
    return new Promise((resolve, reject) => {
        const fr = new FileReader();
        fr.onerror = reject;
        fr.onload = () => {
            resolve(fr.result);
        };
        fr.readAsText(file);
    });
}

export function find_parent(element, selector, start_self = false) {
    while (element.parentNode) {
        if (!start_self) {
            element = element.parentNode;
        }
        if (element instanceof HTMLDocument) {
            return null;
        }
        if (element.matches(selector)) {
            return element;
        }
        if (start_self) {
            element = element.parentNode;
        }
    }

    return null;
}

/**
 * Convert HSV colour to HSL
 *
 * Expects a {0-360}, {0-100}, {0-100} value.
 *
 * @param h
 * @param s
 * @param v
 * @returns {String}
 */
export function hsv2hsl(h, s, v) {
    s /= 100;
    v /= 100;
    const vmin = Math.max(v, 0.01);
    let sl;
    let l;

    l = (2 - s) * v;
    const lmin = (2 - s) * vmin;
    sl = s * vmin;
    sl /= (lmin <= 1) ? lmin : 2 - lmin;
    sl = sl || 0;
    l /= 2;

    return 'hsl(' + h + 'deg, ' + (sl * 100) + '%, ' + (l * 100) + '%)';
}

/**
 * Converts an RGB color value to HSV. Conversion formula
 * adapted from http://en.wikipedia.org/wiki/HSV_color_space.
 * Assumes r, g, and b are contained in the set [0, 255] and
 * returns h, s, and v in the set [0, 1].
 *
 * @param   Number  r       The red color value
 * @param   Number  g       The green color value
 * @param   Number  b       The blue color value
 * @return  Array           The HSV representation
 */
export function rgb2hsv(r, g, b)
{
    r /= 255, g /= 255, b /= 255;

    var max = Math.max(r, g, b), min = Math.min(r, g, b);
    var h, s, v = max;

    var d = max - min;
    s = max == 0 ? 0 : d / max;

    if (max == min) {
        h = 0; // achromatic
    } else {
        switch (max) {
            case r:
                h = (g - b) / d + (g < b ? 6 : 0);
                break;
            case g:
                h = (b - r) / d + 2;
                break;
            case b:
                h = (r - g) / d + 4;
                break;
        }

        h /= 6;
    }

    return [h, s, v];
}

/**
 * Converts an HSV color value to RGB. Conversion formula
 * adapted from http://en.wikipedia.org/wiki/HSV_color_space.
 * Assumes h, s, and v are contained in the set [0, 1] and
 * returns r, g, and b in the set [0, 255].
 *
 * @param   Number  h       The hue
 * @param   Number  s       The saturation
 * @param   Number  v       The value
 * @return  Array           The RGB representation
 */
export function hsv2rgb(h, s, v) {
    var r, g, b;

    var i = Math.floor(h * 6);
    var f = h * 6 - i;
    var p = v * (1 - s);
    var q = v * (1 - f * s);
    var t = v * (1 - (1 - f) * s);

    switch (i % 6) {
        case 0:
            r = v, g = t, b = p;
            break;
        case 1:
            r = q, g = v, b = p;
            break;
        case 2:
            r = p, g = v, b = t;
            break;
        case 3:
            r = p, g = q, b = v;
            break;
        case 4:
            r = t, g = p, b = v;
            break;
        case 5:
            r = v, g = p, b = q;
            break;
    }

    return [r * 255, g * 255, b * 255];
}