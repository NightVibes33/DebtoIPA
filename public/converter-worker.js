const PYODIDE_BASE = 'https://cdn.jsdelivr.net/pyodide/v314.0.2/full/';
let runtimePromise;
let converterSourcePromise;

async function getRuntime() {
  if (!runtimePromise) {
    runtimePromise = (async () => {
      postMessage({ type: 'engine', progress: 8, message: 'Loading the private conversion engine…' });
      const { loadPyodide } = await import(`${PYODIDE_BASE}pyodide.mjs`);
      return loadPyodide({ indexURL: PYODIDE_BASE });
    })();
  }
  return runtimePromise;
}

async function getConverterSource() {
  if (!converterSourcePromise) {
    converterSourcePromise = fetch('/converter.py', { cache: 'force-cache' }).then((response) => {
      if (!response.ok) throw new Error('Could not load the local converter module.');
      return response.text();
    });
  }
  return converterSourcePromise;
}

self.onmessage = async (event) => {
  const { id, buffer, options } = event.data || {};
  if (!id || !(buffer instanceof ArrayBuffer)) return;

  const inputPath = `/tmp/debtoipa-${id}.deb`;
  const outputPath = `/tmp/debtoipa-${id}.zip`;
  try {
    const pyodide = await getRuntime();
    postMessage({ type: 'progress', id, progress: 20, message: 'Opening the Debian archive…' });
    pyodide.FS.writeFile(inputPath, new Uint8Array(buffer));

    const source = await getConverterSource();
    pyodide.runPython(source);
    pyodide.globals.set('debtoipa_input_path', inputPath);
    pyodide.globals.set('debtoipa_output_path', outputPath);
    pyodide.globals.set('debtoipa_options', JSON.stringify(options || {}));

    postMessage({ type: 'progress', id, progress: 46, message: 'Inspecting the app and its executable…' });
    const resultJson = await pyodide.runPythonAsync(`convert_deb(debtoipa_input_path, debtoipa_output_path, debtoipa_options)`);
    postMessage({ type: 'progress', id, progress: 88, message: 'Building the downloadable result…' });

    const bytes = pyodide.FS.readFile(outputPath);
    const transferable = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    postMessage({ type: 'complete', id, result: JSON.parse(resultJson), buffer: transferable }, [transferable]);
  } catch (error) {
    postMessage({ type: 'error', id, message: error instanceof Error ? error.message : String(error) });
  } finally {
    try {
      const pyodide = await runtimePromise;
      if (pyodide) {
        for (const path of [inputPath, outputPath]) {
          try { pyodide.FS.unlink(path); } catch { /* already removed */ }
        }
      }
    } catch { /* runtime failed before initialization */ }
  }
};
