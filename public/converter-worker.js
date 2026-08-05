const PYODIDE_BASE = 'https://cdn.jsdelivr.net/pyodide/v314.0.2/full/';
const HOST_TEMPLATE_URL = 'https://github.com/NightVibes33/DebtoIPA/releases/download/compat-host-v1/DebToIPA-CompatibilityHost-template.ipa';
let runtimePromise;
let sourcePromise;
let hostTemplatePromise;

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

async function textSource(path, label) {
  const response = await fetch(path, { cache: 'force-cache' });
  if (!response.ok) throw new Error(`${label} HTTP ${response.status}.`);
  return response.text();
}

async function getSources() {
  if (!sourcePromise) {
    sourcePromise = Promise.all([
      textSource('/converter.py', 'Direct converter'),
      textSource('/direct_guard.py', 'Whole-package compatibility guard'),
      fetch('/port_mode.py.gz.b64', { cache: 'force-cache' }).then(gunzipBase64),
      textSource('/host_mode.py', 'Compatibility host packager'),
    ]);
  }
  return sourcePromise;
}

async function getHostTemplate() {
  if (!hostTemplatePromise) {
    hostTemplatePromise = fetch(HOST_TEMPLATE_URL, { cache: 'force-cache', redirect: 'follow' }).then(async (response) => {
      if (!response.ok) throw new Error(`Compatibility host template HTTP ${response.status}.`);
      const bytes = new Uint8Array(await response.arrayBuffer());
      if (bytes.length < 1024 || String.fromCharCode(bytes[0], bytes[1]) !== 'PK') {
        throw new Error('Compatibility host template is not a valid IPA archive.');
      }
      return bytes;
    });
  }
  return hostTemplatePromise;
}

self.onmessage = async (event) => {
  const { id, buffer, options } = event.data || {};
  if (!id || !(buffer instanceof ArrayBuffer)) return;
  const inputPath = `/tmp/debtoipa-${id}.deb`;
  const outputPath = `/tmp/debtoipa-${id}.zip`;
  const hostPath = `/tmp/debtoipa-host-${id}.ipa`;
  try {
    const pyodide = await getRuntime();
    postMessage({ type: 'progress', id, progress: 20, message: 'Opening the Debian package…' });
    pyodide.FS.writeFile(inputPath, new Uint8Array(buffer));
    const [directSource, guardSource, portSource, hostSource] = await getSources();
    pyodide.runPython(directSource);
    pyodide.runPython(guardSource);
    pyodide.runPython(portSource);
    pyodide.runPython(hostSource);
    pyodide.globals.set('debtoipa_input_path', inputPath);
    pyodide.globals.set('debtoipa_output_path', outputPath);
    pyodide.globals.set('debtoipa_options', JSON.stringify(options || {}));
    postMessage({ type: 'progress', id, progress: 40, message: 'Auditing every app, helper, daemon, and runtime path…' });
    let resultJson = await pyodide.runPythonAsync('convert_deb_with_port(debtoipa_input_path, debtoipa_output_path, debtoipa_options)');
    let result = JSON.parse(resultJson);

    if (result.verdict === 'port-project' && (options?.mode || 'auto') === 'auto') {
      postMessage({ type: 'progress', id, progress: 68, message: 'Building a launchable stock-iOS compatibility IPA…' });
      const hostTemplate = await getHostTemplate();
      pyodide.FS.writeFile(hostPath, hostTemplate);
      pyodide.globals.set('debtoipa_host_template_path', hostPath);
      resultJson = await pyodide.runPythonAsync(
        'build_host_ipa_from_port_result(debtoipa_output_path, debtoipa_host_template_path, debtoipa_options)'
      );
      result = JSON.parse(resultJson);
    }

    postMessage({ type: 'progress', id, progress: 92, message: 'Finalizing the DebToIPA result…' });
    const bytes = pyodide.FS.readFile(outputPath);
    const transferable = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    postMessage({ type: 'complete', id, result, buffer: transferable }, [transferable]);
  } catch (error) {
    const message = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
    postMessage({ type: 'error', id, message });
  } finally {
    try {
      const pyodide = await runtimePromise;
      if (pyodide) for (const path of [inputPath, outputPath, hostPath]) try { pyodide.FS.unlink(path); } catch {}
    } catch {}
  }
};
