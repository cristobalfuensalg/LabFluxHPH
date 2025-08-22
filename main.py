from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import StreamingResponse, PlainTextResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import pdfplumber, io, re, datetime, tempfile, os, traceback, base64
from docxtpl import DocxTemplate

API_KEY = os.getenv("API_KEY", "")  # opcional: setea en Render para proteger la API

app = FastAPI(title="LabFluxHPH Backend")
app.mount("/static", StaticFiles(directory="static"), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # en producción, restringe a los dominios del hospital
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if API_KEY:
        if request.headers.get("x-api-key") != API_KEY:
            return PlainTextResponse("Unauthorized", status_code=401)
    return await call_next(request)

@app.exception_handler(Exception)
async def all_exception_handler(request, exc):
    tb = traceback.format_exc()
    return PlainTextResponse(tb, status_code=500)

PARAMS_FIJOS = [
    "hto", "hb", "vcm", "hcm", "leuco", "neu", "linfocitos", "mono", "eosin", "basofilos",
    "plaq", "vhs", "glucosa", "glicada", "coltotal", "hdl", "tgl", "bun", "crea",
    "fosforo", "magnesio", "calcio", "calcioion", "acurico",
    "got", "gpt", "ggt", "fa", "bt", "bd",
    "amilasa", "proteinas", "albumina", "amonio", "pcr", "lactico",
    "ldh", "ck", "ckmb", "tropo", "vitd", "vitb",
    "sodio", "potasio", "cloro", "ph", "pcodos", "podos", "bicarb", "base",
    "tp", "inr", "ttpk"
]

ALIASES = {
    r"^HEMATOCRITO$": "hto",
    r"^HEMOGLOBINA$": "hb",
    r"^VCM$": "vcm",
    r"^HCM$": "hcm",
    r"^RCTO DE LEUCOCITOS$": "leuco",
    r"^NEUTR[ÓO]FILOS$": "neu",
    r"^LINFOCITOS$": "linfocitos",
    r"^MONOCITOS$": "mono",
    r"^EOSIN[ÓO]FILOS$": "eosin",
    r"^BAS[ÓO]FILOS$": "basofilos",
    r"^RCTO DE PLAQUETAS$": "plaq",
    r"^VHS$": "vhs",
    r"^GLUCOSA$": "glucosa",
    r"^HEMOGLOBINA GLICOSILADA %$": "glicada",
    r"^COLESTEROL TOTAL$": "coltotal",
    r"^COLESTEROL HDL$": "hdl",
    r"^TRIGLIC[ÉE]RIDOS$": "tgl",
    r"^BUN$": "bun",
    r"^CREATININA$": "crea",
    r"^F[ÓO]SFORO$": "fosforo",
    r"^MAGNESIO$": "magnesio",
    r"^CALCIO$": "calcio",
    r"^CALCIO I[ÓO]NICO$": "calcioion",
    r"^ÁCIDO [ÚU]RICO$": "acurico",
    r"^GOT$": "got",
    r"^GPT$": "gpt",
    r"^GGT$": "ggt",
    r"^FOSFATASA ALCALINA$": "fa",
    r"^BILIRRUBINA TOTAL$": "bt",
    r"^BILIRRUBINA DIRECTA$": "bd",
    r"^AMILASA$": "amilasa",
    r"^PROTE[ÍI]NAS TOTALES$": "proteinas",
    r"^ALB[ÚU]MINA$": "albumina",
    r"^AMONIO$": "amonio",
    r"^PROTE[ÍI]NA C REACTIVA$": "pcr",
    r"^ÁCIDO L[ÁA]CTICO$": "lactico",
    r"^LDH$": "ldh",
    r"^CREATINKINASA TOTAL$": "ck",
    r"^CREATINKINASA MB$": "ckmb",
    r"^TROPONINA T.*$": "tropo",
    r"^NIVELES VITAMINA D$": "vitd",
    r"^NIVELES VITAMINA B12$": "vitb",
    r"^SODIO$": "sodio",
    r"^POTASIO$": "potasio",
    r"^CLORO$": "cloro",
    r"^PH$": "ph",
    r"^P CO2$": "pcodos",
    r"^P O2$": "podos",
    r"^HCO3$": "bicarb",
    r"^EBVT$": "base",
    r"^PORCENTAJE$": "tp",
    r"^INR$": "inr",
    r"^TTPA$": "ttpk"
}

def canon_name(name: str):
    n = name.strip().lower()
    for pat, std in ALIASES.items():
        if re.search(pat, n, flags=re.I):
            return std
    return None

def format_value(std: str, value: str) -> str:
    try:
        val = float(value)
    except:
        return value
    if std == "leuco":
        return str(int(val * 1000))
    if std == "plaq":
        return str(int(val * 1000))
    if std in {"neu", "linfocitos", "mono", "eosin", "basofilos", "tp"}:
        return f"{val:.1f}%"
    return value

def _extract_dt(dstr: str, tstr: str):
    dstr = dstr.replace("-", "/")
    day, month, year = dstr.split("/")
    if len(year) == 2:
        year = "20" + year
    return datetime.datetime(int(year), int(month), int(day),
                             int(tstr.split(":")[0]), int(tstr.split(":")[1]))

def parse_recepcion_datetime(text: str):
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    date_re = r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})"
    time_re = r"(\d{1,2}:\d{2})"

    for ln in lines:
        ln_norm = ln.lower()
        if ("recepci" in ln_norm) and not any(bad in ln_norm for bad in ["muestra", "ingreso", "impres"]):
            m = re.search(date_re + r"\s+" + time_re, ln, flags=re.I)
            if m:
                try:
                    return _extract_dt(m.group(1), m.group(2))
                except:
                    pass
            m2 = re.search(r"fecha.*?" + date_re + r".*?hora.*?" + time_re, ln, flags=re.I)
            if m2:
                try:
                    return _extract_dt(m2.group(1), m2.group(2))
                except:
                    pass

    for i, ln in enumerate(lines):
        ln_norm = ln.lower()
        if ("recepci" in ln_norm) and not any(bad in ln_norm for bad in ["muestra", "ingreso", "impres"]):
            m_date = re.search(date_re, ln, flags=re.I)
            m_time = re.search(time_re, ln, flags=re.I)
            if m_date and m_time:
                try:
                    return _extract_dt(m_date.group(1), m_time.group(1))
                except:
                    pass
            for j in range(i+1, min(i+4, len(lines))):
                m_date2 = re.search(date_re, lines[j], flags=re.I)
                m_time2 = re.search(time_re, lines[j], flags=re.I)
                if m_date2 and m_time2:
                    try:
                        return _extract_dt(m_date2.group(1), m_time2.group(1))
                    except:
                        pass

    for i, ln in enumerate(lines):
        ln_norm = ln.lower()
        if "recepci" in ln_norm:
            m_all = re.search(date_re + r"\s+" + time_re, ln, flags=re.I)
            if m_all:
                try:
                    return _extract_dt(m_all.group(1), m_all.group(2))
                except:
                    pass
            around = lines[max(0, i-1):min(len(lines), i+2)]
            date_found = None
            time_found = None
            for a in around:
                if not date_found:
                    md = re.search(date_re, a, flags=re.I)
                    if md: date_found = md.group(1)
                if not time_found:
                    mt = re.search(time_re, a, flags=re.I)
                    if mt: time_found = mt.group(1)
            if date_found and time_found:
                try:
                    return _extract_dt(date_found, time_found)
                except:
                    pass

    return None

def parse_pdf(file_bytes: bytes):
    rows = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)

    recepcion = parse_recepcion_datetime(text)

    for line in text.splitlines():
        m = re.search(r"^([A-Za-zÁ-ÿ0-9 \-*/+]+?)\s+([*+<>]?\s*[<>]?\d+[.,]?\d*)", line)
        if not m:
            continue
        name = m.group(1).strip()
        value = m.group(2).replace(",", ".").lstrip("*+<> ")
        std = canon_name(name)
        value = format_value(std, value)
        rows.append({
            "std": std,
            "nombre": name,
            "valor": value,
            "recepcion": recepcion,
        })
    return rows

def render_docx(ctx: dict) -> bytes:
    from pathlib import Path
    BASE_DIR = Path(__file__).resolve().parent
    template_path = str(BASE_DIR / "flujograma_template.docx")
    if not os.path.exists(template_path):
        raise HTTPException(500, f"Falta flujograma_template.docx en {template_path}")

    doc = DocxTemplate(template_path)
    doc.render(ctx)
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp_path = tmp.name
    doc.save(tmp_path)
    with open(tmp_path, "rb") as f:
        docx_bytes = f.read()
    os.remove(tmp_path)
    return docx_bytes

def convert_docx_to_pdf(docx_bytes: bytes) -> bytes:
    # 1) Si hay Word en Windows y docx2pdf está disponible
    try:
        from docx2pdf import convert as docx2pdf_convert  # por si no lo importaste arriba
        DOCX2PDF_AVAILABLE_LOCAL = True
    except Exception:
        DOCX2PDF_AVAILABLE_LOCAL = False

    if DOCX2PDF_AVAILABLE_LOCAL:
        try:
            with tempfile.TemporaryDirectory() as td:
                in_path = os.path.join(td, "out.docx")
                out_path = os.path.join(td, "out.pdf")
                with open(in_path, "wb") as f:
                    f.write(docx_bytes)
                docx2pdf_convert(in_path, out_path)
                with open(out_path, "rb") as f:
                    return f.read()
        except Exception:
            pass  # si falla, seguimos con LibreOffice

    # 2) LibreOffice (Windows o Linux)
    possible_paths = [
        r"C:\\Program Files\\LibreOffice\\program\\soffice.exe",   # Windows
        "/usr/bin/soffice",                                       # Linux (Render)
        "/usr/lib/libreoffice/program/soffice",                   # Otra ruta Linux
        "/snap/bin/libreoffice",                                  # Instalación vía Snap
    ]
    for soffice in possible_paths:
        if os.path.exists(soffice):
            try:
                with tempfile.TemporaryDirectory() as td:
                    in_path = os.path.join(td, "out.docx")
                    with open(in_path, "wb") as f:
                        f.write(docx_bytes)
                    os.system(f"\"{soffice}\" --headless --convert-to pdf --outdir \"{td}\" \"{in_path}\"")
                    out_path = os.path.join(td, "out.pdf")
                    if os.path.exists(out_path):
                        with open(out_path, "rb") as f:
                            return f.read()
            except Exception:
                pass

    # 3) Si no se pudo convertir, devolvemos None para que el endpoint haga fallback
    return None

@app.get("/health")
def health():
    return {"ok": True}

def extract_pdfs_from_uploads(files: list[UploadFile]) -> list[bytes]:
    """
    Recibe UploadFiles (PDFs o ZIPs).
    Devuelve una lista de bytes de PDFs para procesar.
    """
    import zipfile
    pdf_bytes_list = []
    for uf in files:
        content = uf.file.read() if hasattr(uf, "file") else None
        if content is None or len(content) == 0:
            continue
        filename = (uf.filename or "").lower()
        if filename.endswith(".zip"):
            # Descomprimir y tomar PDFs
            with io.BytesIO(content) as bio:
                with zipfile.ZipFile(bio) as zf:
                    for name in zf.namelist():
                        if name.lower().endswith(".pdf"):
                            with zf.open(name) as zpdf:
                                pdf_bytes_list.append(zpdf.read())
        elif filename.endswith(".pdf"):
            pdf_bytes_list.append(content)
        else:
            # Ignora otros formatos
            pass
    return pdf_bytes_list

def build_context(all_rows):
    tandas = {}
    extras_detectados = set()
    for r in all_rows:
        if not r["recepcion"]:
            continue
        key = r["recepcion"].strftime("%Y-%m-%d %H:%M")
        if key not in tandas:
            tandas[key] = {}
        if r["std"]:
            tandas[key][r["std"]] = r["valor"]
        else:
            extras_detectados.add(r["nombre"])

    fechas = sorted(tandas.keys())[:8]
    ctx = {}
    for i, fecha in enumerate(fechas, start=1):
        dt = datetime.datetime.strptime(fecha, "%Y-%m-%d %H:%M")
        ctx[f"fecha_{i}"] = dt.strftime("%d/%m/%Y")
        ctx[f"hora_{i}"]  = dt.strftime("%H:%M")
        for param in ALIASES.values():
            ctx[f"{param}_{i}"] = tandas[fecha].get(param, "")
    for i in range(len(fechas)+1, 9):
        ctx[f"fecha_{i}"] = ""
        ctx[f"hora_{i}"]  = ""
        for param in ALIASES.values():
            ctx[f"{param}_{i}"] = ""
    return ctx

@app.get("/", response_class=HTMLResponse)
def index():
    return """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LabFluxHPH – Interfaz Mejorada</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@500;700&display=swap" rel="stylesheet">
  <style>
    body { font-family: 'Poppins', sans-serif; }
  </style>
</head>
<body class="bg-gray-100">
  <!-- Barra superior azul con título y GIFs -->
  <header class="bg-blue-900 text-white py-4 flex items-center justify-center gap-6">
    <img src="/static/gatosaludando.gif" alt="decorativo izquierda" class="h-16 w-16">
    <h1 class="text-4xl font-bold">LabFluxHPH</h1>
    <img src="/static/gatosaludando.gif" alt="decorativo derecha" class="h-16 w-16">
  </header>

  <!-- Contenedor principal -->
  <div class="max-w-xl mx-auto mt-8 p-6 bg-white rounded-2xl shadow-lg transition-all">
    <p class="text-gray-700 text-center mb-6">
      Sube 1 o más PDFs con resultados de laboratorio y recibe tu flujograma listo.
    </p>

    <label id="dropzone"
      class="block border-2 border-dashed border-gray-400 rounded-2xl p-12 text-center cursor-pointer hover:border-blue-600 transition-all duration-300">
      <div class="text-blue-400 text-5xl mb-4">📄</div>
      <div class="text-gray-600 font-semibold">Arrastra archivos aquí o haz clic para seleccionarlos</div>
      <input type="file" multiple accept=".pdf,.zip" class="hidden">
    </label>

    <div id="fileList" class="mt-4 flex flex-wrap gap-2"></div>

    <div class="mt-6 text-center">
      <div id="status" class="text-gray-700 mb-4 relative h-8"></div>
      <div class="flex justify-center space-x-4">
        <button id="generateBtn"
          class="bg-blue-900 text-white px-6 py-2 rounded-2xl font-medium hover:bg-blue-800 transition-all duration-200">
          Generar flujograma
        </button>
        <button id="clearBtn"
          class="bg-gray-500 text-white px-6 py-2 rounded-2xl font-medium hover:bg-gray-400 transition-all duration-200">
          Limpiar
        </button>
      </div>
    </div>
  </div>

  <script>
    const dropzone = document.getElementById('dropzone');
    const fileInput = dropzone.querySelector('input[type="file"]');
    const fileList = document.getElementById('fileList');
    const status = document.getElementById('status');
    const generateBtn = document.getElementById('generateBtn');
    const clearBtn = document.getElementById('clearBtn');

    function renderFiles() {
      fileList.innerHTML = '';
      Array.from(fileInput.files).forEach(file => {
        const div = document.createElement('div');
        div.className = 'bg-blue-100 text-blue-800 px-3 py-1 rounded-full text-sm';
        div.textContent = `${file.name} · ${(file.size / 1024).toFixed(1)} KB`;
        fileList.appendChild(div);
      });
    }

    function setSpinner(show) {
      status.innerHTML = show
        ? '<img src="/static/loading.gif" alt="Cargando..." class="mx-auto h-8">'
        : '';
    }

    dropzone.addEventListener('click', () => fileInput.click());
    dropzone.addEventListener('dragover', e => {
      e.preventDefault();
      dropzone.classList.add('border-blue-600');
    });
    dropzone.addEventListener('dragleave', () => dropzone.classList.remove('border-blue-600'));
    dropzone.addEventListener('drop', e => {
      e.preventDefault();
      dropzone.classList.remove('border-blue-600');
      fileInput.files = e.dataTransfer.files;
      renderFiles();
    });

    fileInput.addEventListener('change', renderFiles);

    clearBtn.addEventListener('click', () => {
      fileInput.value = '';
      fileList.innerHTML = '';
      status.innerHTML = '';
    });

    generateBtn.addEventListener('click', async () => {
      if (!fileInput.files.length) {
        status.innerHTML = '<span class="text-red-500">⚠ Selecciona al menos un archivo.</span>';
        return;
      }

      setSpinner(true);
      status.innerHTML = '';

      const fd = new FormData();
      Array.from(fileInput.files).forEach(f => fd.append('files', f));

      try {
        const res = await fetch('/generate', { method: 'POST', body: fd });
        if (!res.ok) throw new Error(await res.text());
        const blob = await res.blob();
        const cd = res.headers.get('Content-Disposition') || '';
        const name = /filename="?([^";]+)"?/.exec(cd)?.[1] || 'LabFluxHPH.docx';

        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = name;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);

        status.innerHTML = '<span class="text-green-600">Flujograma generado. Revisa tu descarga.</span>';
      } catch (error) {
        status.innerHTML = `<span class="text-red-500">❌ ${error.message}</span>`;
      } finally {
        setSpinner(false);
      }
    });
  </script>
</body>
</html>
"""
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>LabFluxHPH</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #f4f4f5;
    --text: #111827;
    --muted: #6b7280;
    --primary: #1d4ed8;
    --primary-dark: #1e40af;
    --danger: #dc2626;
    --success: #059669;
    --card: #fff;
    --border: #e5e7eb;
  }
  body {
    font-family: 'Inter', sans-serif;
    margin: 0;
    padding: 0;
    background-color: var(--bg);
    color: var(--text);
  }
  .container {
    max-width: 800px;
    margin: 40px auto;
    background: var(--card);
    padding: 24px;
    border-radius: 16px;
    box-shadow: 0 2px 10px rgba(0,0,0,0.05);
    border: 1px solid var(--border);
  }
  h1 {
    font-size: 24px;
    font-weight: 600;
    margin-bottom: 8px;
  }
  p.sub {
    color: var(--muted);
    margin-bottom: 24px;
  }
  .upload-area {
    border: 2px dashed var(--border);
    border-radius: 12px;
    padding: 20px;
    text-align: center;
    background: #f9fafb;
    transition: background 0.2s, border-color 0.2s;
  }
  .upload-area.drag {
    background: #eff6ff;
    border-color: #93c5fd;
  }
  input[type="file"] {
    display: none;
  }
  .buttons {
    display: flex;
    gap: 10px;
    margin-top: 16px;
  }
  button {
    background-color: var(--primary);
    color: white;
    border: none;
    border-radius: 8px;
    padding: 10px 16px;
    font-weight: 600;
    cursor: pointer;
  }
  button:hover {
    background-color: var(--primary-dark);
  }
  button.secondary {
    background-color: #6b7280;
  }
  .status {
    margin-top: 16px;
    font-size: 14px;
  }
  .status.ok { color: var(--success); }
  .status.err { color: var(--danger); white-space: pre-wrap; }
  .file-list {
    margin-top: 12px;
    font-size: 14px;
    color: var(--muted);
  }
  .tag {
    background: #e0e7ff;
    color: #1e3a8a;
    border-radius: 999px;
    padding: 4px 10px;
    font-size: 12px;
    margin: 4px;
    display: inline-block;
  }
</style>
</head>
<body>
<div class="container">
  <h1 style="display: flex; align-items: center; gap: 10px;">
  LabFluxHPH
  <img src="/static/gatosaludando.gif" alt="logo" style="height: 36px;">
</h1>
  <p class="sub">Sube tus archivos de laboratorio (PDF o ZIP) para generar el flujograma automáticamente.</p>

  <label id="drop" class="upload-area">
    <input id="fileInput" type="file" name="files" multiple accept=".pdf,.zip">
    <div><strong>Arrastra aquí los archivos</strong> o haz clic para seleccionarlos</div>
    <div class="file-list" id="fileList"></div>
  </label>

  <div class="buttons">
    <button id="btn">Generar</button>
    <button id="clearBtn" class="secondary">Limpiar</button>
  </div>

  <div id="status" class="status"></div>
</div>

<script>
const drop = document.getElementById('drop');
const input = document.getElementById('fileInput');
const fileList = document.getElementById('fileList');
const btn = document.getElementById('btn');
const clearBtn = document.getElementById('clearBtn');
const statusBox = document.getElementById('status');

function renderFiles() {
  fileList.innerHTML = input.files.length
    ? Array.from(input.files).map(f => {
        const kb = Math.round((f.size / 1024) * 10) / 10;
        return `<span class="tag">${f.name} · ${kb} KB</span>`;
      }).join('')
    : '';
}

drop.addEventListener('click', () => input.click());
drop.addEventListener('dragover', e => {
  e.preventDefault();
  drop.classList.add('drag');
});
drop.addEventListener('dragleave', () => drop.classList.remove('drag'));
drop.addEventListener('drop', e => {
  e.preventDefault();
  drop.classList.remove('drag');
  if (e.dataTransfer.files.length) {
    input.files = e.dataTransfer.files;
    renderFiles();
  }
});
input.addEventListener('change', renderFiles);
clearBtn.addEventListener('click', () => {
  input.value = '';
  renderFiles();
  statusBox.innerHTML = '';
});

btn.addEventListener('click', async () => {
  if (!input.files.length) {
    statusBox.innerHTML = '<span class="err">⚠️ Selecciona al menos un archivo.</span>';
    return;
  }
  btn.disabled = true;
  statusBox.innerHTML = '⏳ Procesando...';

  const fd = new FormData();
  Array.from(input.files).forEach(f => fd.append('files', f));

  try {
    const res = await fetch('/generate', { method: 'POST', body: fd });
    if (!res.ok) throw new Error(await res.text());
    const cd = res.headers.get('Content-Disposition') || '';
    const fname = /filename="?([^";]+)"?/.exec(cd)?.[1] || 'LabFluxHPH.docx';
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = fname;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
    statusBox.innerHTML = '<span class="ok">✅ Flujograma generado.</span>';
  } catch (e) {
    statusBox.innerHTML = '<span class="err">❌ Error:\n' + (e.message || e) + '</span>';
  } finally {
    btn.disabled = false;
  }
});
</script>
</body>
</html>
"""

@app.post("/generate")
async def generate(files: list[UploadFile] = File(...)):
    if not files:
        raise HTTPException(400, "Sube al menos un PDF.")

    all_rows = []
    pdf_bytes_list = extract_pdfs_from_uploads(files)
    if not pdf_bytes_list:
        raise HTTPException(400, "No se encontraron PDFs válidos.")
    for content in pdf_bytes_list:
        all_rows.extend(parse_pdf(content))

    ctx = build_context(all_rows)
    docx_bytes = render_docx(ctx)

    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="LabFluxHPH.docx"'}
    )

    # Fallback a DOCX si no hay conversión disponible
    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="LabFluxHPH.docx"'}
    )

@app.post("/generate_json")
async def generate_json(files: list[UploadFile] = File(...)):
    if not files:
        raise HTTPException(400, "Sube al menos un PDF.")

    all_rows = []
    pdf_bytes_list = extract_pdfs_from_uploads(files)
    if not pdf_bytes_list:
        raise HTTPException(400, "No se encontraron PDFs válidos.")
    for content in pdf_bytes_list:
        all_rows.extend(parse_pdf(content))

    ctx = build_context(all_rows)
    docx_bytes = render_docx(ctx)

    data_b64 = base64.b64encode(docx_bytes).decode("ascii")
    return {
        "filename": "LabFluxHPH.docx",
        "mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "data_base64": data_b64,
        "notes": "OK (DOCX)"
    }

    # Fallback a DOCX si no hay conversión disponible
    data_b64 = base64.b64encode(docx_bytes).decode("ascii")
    return {
        "filename": "LabFluxHPH.docx",
        "mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "data_base64": data_b64,
        "notes": "No se pudo convertir a PDF; se entrega DOCX"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
