const PYODIDE_BASE = 'https://cdn.jsdelivr.net/pyodide/v314.0.2/full/';
let runtimePromise;
let sourcePromise;

async function gunzipBase64(response) {
  if (!response.ok) throw new Error(`Port Mode engine HTTP ${response.status}.`);
  const encoded = await response.text();
  const bytes = Uint8Array.from(atob(encoded.trim()), (value) => value.charCodeAt(0));
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
  return new Response(stream).text();
}

async function getRuntime() {
  if (!runtimePromise) {
    runtimePromise = (async () => {
      postMessage({ type: 'engine', progress: 8, message: 'Loading the DebToIPA engine…' });
      const { loadPyodide } = await import(`${PYODIDE_BASE}pyodide.mjs`);
      return loadPyodide({ indexURL: PYODIDE_BASE });
    })();
  }
  return runtimePromise;
}

async function getSources() {
  if (!sourcePromise) {
    sourcePromise = Promise.all([
      fetch('/converter.py', { cache: 'force-cache' }).then((response) => {
        if (!response.ok) throw new Error(`Direct converter HTTP ${response.status}.`);
        return response.text();
      }),
      fetch('/port_mode.py.gz.b64', { cache: 'force-cache' }).then(gunzipBase64),
    ]);
  }
  return sourcePromise;
}

self.onmessage = async (event) => {
  const { id, buffer, options } = event.data || {};
  if (!id || !(buffer instanceof ArrayBuffer)) return;
  const inputPath = `/tmp/debtoipa-${id}.deb`;
  const outputPath = `/tmp/debtoipa-${id}.zip`;
  try {
    const pyodide = await getRuntime();
    postMessage({ type: 'progress', id, progress: 20, message: 'Opening the Debian package…' });
    pyodide.FS.writeFile(inputPath, new Uint8Array(buffer));
    const [directSource, portSource] = await getSources();
    pyodide.runPython(directSource);
    pyodide.runPython(portSource);
    pyodide.globals.set('debtoipa_input_path', inputPath);
    pyodide.globals.set('debtoipa_output_path', outputPath);
    pyodide.globals.set('debtoipa_options', JSON.stringify(options || {}));
    postMessage({ type: 'progress', id, progress: 46, message: 'Classifying direct and jailbreak components…' });
    const resultJson = await pyodide.runPythonAsync('convert_deb_with_port(debtoipa_input_path, debtoipa_output_path, debtoipa_options)');
    postMessage({ type: 'progress', id, progress: 88, message: 'Building the DebToIPA result…' });
    const bytes = pyodide.FS.readFile(outputPath);
    const transferable = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    postMessage({ type: 'complete', id, result: JSON.parse(resultJson), buffer: transferable }, [transferable]);
  } catch (error) {
    const message = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
    postMessage({ type: 'error', id, message });
  } finally {
    try {
      const pyodide = await runtimePromise;
      if (pyodide) for (const path of [inputPath, outputPath]) try { pyodide.FS.unlink(path); } catch {}
    } catch {}
  }
};
