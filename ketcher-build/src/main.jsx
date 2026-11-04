import './shim.js';
import React from 'react';
import { createRoot } from 'react-dom/client';
import { Editor } from 'ketcher-react';
import { StandaloneStructServiceProvider } from 'ketcher-standalone/dist/binaryWasmNoRender';
import 'ketcher-react/dist/index.css';

const provider = new StandaloneStructServiceProvider();
// Parent page reads window.ketcher (same origin) and waits for the 'ketcher-ready' message.
createRoot(document.getElementById('root')).render(
  <Editor
    staticResourcesUrl="."
    structServiceProvider={provider}
    errorHandler={(m) => console.error('ketcher', m)}
    disableMacromoleculesEditor
    onInit={(k) => { window.ketcher = k; try { window.parent.postMessage({ type: 'ketcher-ready' }, '*'); } catch (e) {} }}
  />
);
