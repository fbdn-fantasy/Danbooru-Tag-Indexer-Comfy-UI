const events = new EventTarget();
export const api = {
    fetchApi: (path, options) => fetch(path, options),
    addEventListener: (...args) => events.addEventListener(...args),
};
