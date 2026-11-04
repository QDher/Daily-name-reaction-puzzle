// ketcher-core calls require('raphael') at load time; provide it in the browser bundle.
import Raphael from 'raphael';
globalThis.require = (name) => { if (name === 'raphael') return Raphael; throw new Error('require(' + name + ') not available'); };
