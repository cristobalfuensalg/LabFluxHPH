from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import StreamingResponse, PlainTextResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import pdfplumber, io, re, datetime, tempfile, os, traceback
from docxtpl import DocxTemplate
import base64

API_KEY = os.getenv("API_KEY", "")

app = FastAPI(title="LabFluxHPH Backend")
app.mount("/static", StaticFiles(directory="static"), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

# -----------------------
# Config de parámetros
# -----------------------
PARAMS_FIJOS = [
    "hto", "hb", "vcm", "hcm", "leuco", "neu", "linfocitos", "mono", "eosin", "basofilos",
    "plaq", "vhs", "glucosa", "glicada", "coltotal", "hdl", "ldl", "tgl", "bun", "crea", "buncrea", "vfg",
    "fosforo", "magnesio", "calcio", "calcioion", "acurico",
    "got", "gpt", "ggt", "fa", "bt", "bd",
    "amilasa", "proteinas", "albumina", "pcr", "lactico",
    "ldh", "ck", "ckmb", "tropo", "vitd", "vitb",
    "sodio", "potasio", "cloro", "ph", "pcodos", "podos", "bicarb", "base",
    "tp", "inr", "ttpk",
    # Orina completa
    "coloroc", "aspectooc", "densoc", "phoc", "nitritosoc", "protoc", "cetonasoc",
    "glucosaoc", "urobiloc", "bilioc", "mucusoc", "leucosoc", "groc", "bactoc",
    "hialoc", "granuloc", "epiteloc", "cristaloc", "levadoc",
    # Cultivo (placeholders específicos)
    "fechacul", "horacul", "fechaposcul", "horaposcul", "muestra", "gram", "agente", "ATB"
]

# -----------------------
# Detección de panel por página
# -----------------------
SECTION_MARKERS = {
    "oc": [
        r"ORINA\s+COMPLETA",
        r"\bSED\.?U\b",
        r"\bUROAN[ÁA]LISIS\b",
        r"\bEXAMEN\s+DE\s+ORINA\b",
    ],
    "cultivo": [
        r"\bCULTIVO\b", r"\bUROCULTIVO\b", r"\bHEMOCULTIVO\b",
        r"\bANTIBIOGRAMA\b", r"\bTINCION\s+DE\s+GRAM\b", r"\bGRAM\b"
    ],
    "resto": []
}

ALIAS_BY_PANEL = {
    "resto": {
        r"^HEMATOCRITO$": "hto",
        r"^HEMOGLOBINA$": "hb",
        r"^VCM$": "vcm",
        r"^HCM$": "hcm",
        r"^RCTO DE LEUCOCITOS$": "leuco",
        r"^LEUCOCITOS$": "leuco",
        r"^NEUTR[ÓO]FILOS$": "neu",
        r"^LINFOCITOS$": "linfocitos",
        r"^MONOCITOS$": "mono",
        r"^EOSIN[ÓO]FILOS$": "eosin",
        r"^BAS[ÓO]FILOS$": "basofilos",
        r"^RCTO DE PLAQUETAS$": "plaq",
        r"^PLAQUETAS$": "plaq",
        r"^VHS$": "vhs",
        r"^GLUCOSA$": "glucosa",
        r"^HEMOGLOBINA GLICOSILADA %$": "glicada",
        r"^COLESTEROL TOTAL$": "coltotal",
        r"^COLESTEROL HDL$": "hdl",
        r"^COLESTEROL LDL$": "ldl",
        r"^TRIGLIC[ÉE]RIDOS$": "tgl",
        r"^BUN$": "bun",
        r"^UREA$": "bun",
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
        r"^EBVT$": "base",        # Base Excess
        r"^EXCESO DE BASE$": "base",
        r"^PORCENTAJE$": "tp",
        r"^INR$": "inr",
        r"^TTPA$": "ttpk",
    },
    "oc": {
        r"^COLOR$": "coloroc",
        r"^ASPECTO$": "aspectooc",
        r"^DENSIDAD$": "densoc",
        r"^PH$": "phoc",
        r"^NITRITOS$": "nitritosoc",
        r"^PROTE[IÍ]NAS?$": "protoc",
        r"^CETONAS$": "cetonasoc",
        r"^GLUCOSA$": "glucosaoc",
        r"^UROBILIN[ÓO]GENO$": "urobiloc",
        r"^BILIRRUBINA$": "bilioc",
        r"^MUCUS$": "mucusoc",
        r"^LEUCOCITOS$": "leucosoc",
        r"^(GL[ÓO]BULOS ROJOS|ERITROCITOS)$": "groc",
        r"^BACTERIAS$": "bactoc",
        r"^CILINDROS HIALINOS$": "hialoc",
        r"^CILINDROS GRANULOSOS$": "granuloc",
        r"^C[EÉ]LULAS EPITELIALES$": "epiteloc",
        r"^CRISTALES$": "cristaloc",
        r"^LEVADURAS$": "levadoc",
    },
    "cultivo": {
        r"^TINCION DE GRAM$": "gram",
        r"^ANTIBIOGRAMA$": "ATB",
        r"^MICROORGANISMO$": "agente",
        r"^MUESTRA:?$": "muestra",
        r"^Muestra:$": "muestra",
    }
}

# -----------------------
# Utilidades
# -----------------------
def detect_panel_page(text: str) -> str:
    """Detecta el panel de una página por marcadores y, si no, por heurísticas."""
    for panel, pats in SECTION_MARKERS.items():
        for pat in pats:
            if re.search(pat, text, flags=re.I):
                return panel
    # Heurística secundaria
    text_low = text.lower()
    oc_hits = any(k in text_low for k in [
        "orina completa", "sed.u", "sed u", "uroan", "urobil", "cilindros", "bacterias", "leucocitos en orina"
    ])
    cultivo_hits = any(k in text_low for k in [
        "urocultivo", "hemocultivo", "antibiograma", "gram", "tinción de gram", "cultivo"
    ])
    if oc_hits and not cultivo_hits:
        return "oc"
    if cultivo_hits:
        return "cultivo"
    return "resto"

def match_alias_in_panel(name: str, panel: str) -> str | None:
    """Primero intenta alias del panel; si no, cae a 'resto' para términos globales."""
    for pat, std in ALIAS_BY_PANEL.get(panel, {}).items():
        if re.search(pat, name, flags=re.I):
            return std
    if panel != "resto":
        for pat, std in ALIAS_BY_PANEL["resto"].items():
            if re.search(pat, name, flags=re.I):
                return std
    return None

def heuristic_alias(name: str, panel: str) -> str | None:
    """Heurísticas por 'contains' cuando no hay match exacto."""
    n = name.lower().strip()
    if panel == "oc":
        tests = [
            ("color", "coloroc"), ("aspect", "aspectooc"), ("densid", "densoc"),
            (" ph", "phoc"), ("ph ", "phoc"), ("nitrit", "nitritosoc"),
            ("prote", "protoc"), ("ceton", "cetonasoc"), ("gluco", "glucosaoc"),
            ("urobil", "urobiloc"), ("bilir", "bilioc"), ("muc", "mucusoc"),
            ("leuco", "leucosoc"), ("eritro", "groc"), ("globulos rojos", "groc"),
            ("bacter", "bactoc"), ("hial", "hialoc"), ("granul", "granuloc"),
            ("epitel", "epiteloc"), ("cristal", "cristaloc"), ("levad", "levadoc")
        ]
        for sub, std in tests:
            if sub in n:
                return std
        return None
    if panel == "cultivo":
        tests = [
            ("gram", "gram"), ("antibio", "ATB"),
            ("microorgan", "agente"), ("agente", "agente"),
            ("muestra", "muestra")
        ]
        for sub, std in tests:
            if sub in n:
                return std
        return None
    # resto
    tests = [
        ("hematoc", "hto"), ("hemogl", "hb"), ("vcm", "vcm"), ("hcm", "hcm"),
        ("leuco", "leuco"), ("neutro", "neu"), ("linfo", "linfocitos"),
        ("monoc", "mono"), ("eosin", "eosin"), ("baso", "basofilos"),
        ("plaquet", "plaq"), ("vhs", "vhs"),
        ("glucosa", "glucosa"), ("glicos", "glicada"),
        ("colesterol total", "coltotal"), ("hdl", "hdl"), ("ldl", "ldl"),
        ("triglic", "tgl"), ("urea", "bun"), ("bun", "bun"), ("creatin", "crea"),
        ("fosforo", "fosforo"), ("magnesio", "magnesio"), ("calcio i", "calcioion"),
        ("calcio", "calcio"), ("acido urico", "acurico"),
        ("got", "got"), ("gpt", "gpt"), ("ggt", "ggt"), ("fosfatasa alcalina", "fa"),
        ("bilirrubina total", "bt"), ("bilirrubina directa", "bd"),
        ("amilasa", "amilasa"), ("proteina c reactiva", "pcr"), ("proteinas totales", "proteinas"),
        ("albumin", "albumina"), ("lactico", "lactico"), ("ldh", "ldh"),
        ("ckmb", "ckmb"), ("creatinquinasa", "ck"), ("troponina", "tropo"),
        ("vitamina d", "vitd"), ("vitamina b12", "vitb"),
        ("sodio", "sodio"), ("potasio", "potasio"), ("cloro", "cloro"),
        (" p co2", "pcodos"), (" p o2", "podos"), ("hco3", "bicarb"),
        ("exceso de base", "base"), ("ebvt", "base"),
        ("porcentaje", "tp"), ("inr", "inr"), ("ttpa", "ttpk"),
        (" ph", "ph"), ("ph ", "ph")
    ]
    for sub, std in tests:
        if sub in n:
            return std
    return None

def coalesce_alias(name: str, panel: str) -> str | None:
    std = match_alias_in_panel(name, panel)
    if std:
        return std
    return heuristic_alias(name, panel)

def extract_numeric_head(s: str) -> str:
    """Obtiene el primer número (con coma o punto) de una cadena, o retorna s si no hay número."""
    m = re.search(r"[-+]?\d+(?:[.,]\d+)?", s)
    return (m.group(0) if m else s).strip()

def format_value(std: str | None, value: str) -> str:
    """
    - leucocitos/plaquetas en miles:
      * si < 1000 -> multiplica por 1000
      * si >= 1000 -> deja tal cual
    - % para dif y TP
    """
    if not std:
        return value
    # intenta numérico
    cand = value.replace(",", ".")
    try:
        val = float(cand)
    except:
        return value

    if std in {"leuco", "plaq"}:
        if val < 1000:
            return str(int(round(val * 1000)))
        return str(int(round(val)))
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
    """
    Busca solo 'Recepción' (evita muestra/ingreso/impresión).
    """
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
            date_found, time_found = None, None
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

# -----------------------
# Parser por página
# -----------------------
def parse_pdf(file_bytes: bytes):
    """
    Paso 2: parseo por página con panel/contexto independiente, alias por panel + heurísticas,
    y Fecha/Hora de Recepción por página (cultivo -> genera fechacul/horacul).
    """
    rows = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page_index, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if not text.strip():
                continue

            panel = detect_panel_page(text)
            recepcion = parse_recepcion_datetime(text)

            # Cultivo: generar placeholders específicos desde la Recepción de esta página
            if panel == "cultivo" and recepcion:
                rows.append({
                    "std": "fechacul",
                    "nombre": "Fecha Recepción Cultivo",
                    "valor": recepcion.strftime("%d/%m/%Y"),
                    "recepcion": recepcion,
                    "panel": panel,
                    "page_index": page_index
                })
                rows.append({
                    "std": "horacul",
                    "nombre": "Hora Recepción Cultivo",
                    "valor": recepcion.strftime("%H:%M"),
                    "recepcion": recepcion,
                    "panel": panel,
                    "page_index": page_index
                })

            # Recorrer líneas de la página
            for raw in text.splitlines():
                line = raw.strip()
                if not line:
                    continue

                # Separación típica: columnas con 2+ espacios o con ':'
                parts = re.split(r"\s{2,}", line)
                if len(parts) < 2:
                    if ":" in line:
                        parts = [p.strip() for p in line.split(":", 1)]
                    else:
                        continue

                name = parts[0].strip()
                value = parts[1].strip()

                # Valor: intenta extraer número al inicio si corresponde
                numeric_candidate = extract_numeric_head(value)
                # Coalesce alias con prioridad de panel
                std = coalesce_alias(name, panel)

                # Formato según estándar
                value_fmt = format_value(std, numeric_candidate if numeric_candidate else value)

                rows.append({
                    "std": std,
                    "nombre": name,
                    "valor": value_fmt,
                    "recepcion": recepcion,
                    "panel": panel,
                    "page_index": page_index
                })

    return rows

# -----------------------
# DOCX y endpoints
# -----------------------
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

@app.get("/health")
def health():
    return {"ok": True}

def extract_pdfs_from_uploads(files: list[UploadFile]) -> list[bytes]:
    import zipfile
    pdf_bytes_list = []
    for uf in files:
        content = uf.file.read() if hasattr(uf, "file") else None
        if content is None or len(content) == 0:
            continue
        filename = (uf.filename or "").lower()
        if filename.endswith(".zip"):
            with io.BytesIO(content) as bio:
                with zipfile.ZipFile(bio) as zf:
                    for name in zf.namelist():
                        if name.lower().endswith(".pdf"):
                            with zf.open(name) as zpdf:
                                pdf_bytes_list.append(zpdf.read())
        elif filename.endswith(".pdf"):
            pdf_bytes_list.append(content)
    return pdf_bytes_list

def build_context(all_rows):
    """
    Agrupa por tandas según fecha/hora de Recepción (por página).
    Solo usamos Recepción; sin ella, la fila no se considera en el flujograma.
    """
    tandas: dict[str, dict] = {}
    extras_detectados = set()

    for r in all_rows:
        rec = r.get("recepcion")
        if not rec:
            continue
        key = rec.strftime("%Y-%m-%d %H:%M")
        if key not in tandas:
            tandas[key] = {}
        std = r.get("std")
        if std:
            tandas[key][std] = r.get("valor", "")
        else:
            extras_detectados.add(r.get("nombre", ""))

    # Orden cronológico (máx 8 columnas)
    fechas = sorted(tandas.keys())[:8]
    ctx = {}
    for i, fecha in enumerate(fechas, start=1):
        dt = datetime.datetime.strptime(fecha, "%Y-%m-%d %H:%M")
        ctx[f"fecha_{i}"] = dt.strftime("%d/%m/%Y")
        ctx[f"hora_{i}"] = dt.strftime("%H:%M")
        for param in PARAMS_FIJOS:
            ctx[f"{param}_{i}"] = tandas[fecha].get(param, "")

    # Rellenar columnas vacías restantes
    for i in range(len(fechas) + 1, 9):
        ctx[f"fecha_{i}"] = ""
        ctx[f"hora_{i}"] = ""
        for param in PARAMS_FIJOS:
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
    <style> body { font-family: 'Poppins', sans-serif; } </style>
</head>
<body class="bg-gray-100">
    <header class="bg-blue-900 text-white py-4 flex items-center justify-center gap-6">
        <img src="/static/gatosaludando.gif" alt="decorativo izquierda" class="h-16 w-16">
        <h1 class="text-4xl font-bold">LabFluxHPH</h1>
        <img src="/static/gatosaludando.gif" alt="decorativo derecha" class="h-16 w-16">
    </header>

    <div class="max-w-xl mx-auto mt-8 p-6 bg-white rounded-2xl shadow-lg transition-all">
        <p class="text-gray-700 text-center mb-6">
            Sube 1 o más PDFs con resultados de laboratorio y recibe tu flujograma listo.
        </p>

    <input id="fileInput" type="file" multiple accept=".pdf,.zip" class="hidden" />

    <div id="dropzone"
         class="border-2 border-dashed border-gray-400 rounded-2xl p-12 text-center cursor-pointer hover:border-blue-600 transition-all duration-300">
      <div class="text-blue-400 text-5xl mb-4">📄</div>
      <div class="text-gray-600 font-semibold">Arrastra archivos aquí o haz clic para seleccionarlos</div>
      <button id="browseBtn" type="button"
              class="mt-4 inline-flex items-center px-4 py-1.5 rounded-lg bg-blue-100 text-blue-700 hover:bg-blue-200 transition">
        Seleccionar archivos
      </button>
    </div>

    <div id="fileList" class="mt-4 flex flex-wrap gap-2"></div>

    <div class="mt-6 text-center space-y-3">
      <div class="text-center space-y-2">
        <img id="spinner" src="/static/loading.gif" alt="Cargando..." class="mx-auto h-8 hidden">
        <div id="status" class="text-gray-700 min-h-6"></div>
      </div>

      <div id="progressWrap" class="w-full bg-gray-200 rounded-full h-3 overflow-hidden hidden">
        <div id="progressBar" class="bg-blue-600 h-3 w-0 transition-all duration-150"></div>
      </div>
      <div id="progressText" class="text-sm text-gray-600 hidden">0%</div>

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
    const dropzone     = document.getElementById('dropzone');
    const browseBtn    = document.getElementById('browseBtn');
    const fileInput    = document.getElementById('fileInput');
    const fileList     = document.getElementById('fileList');
    const statusBox    = document.getElementById('status');
    const generateBtn  = document.getElementById('generateBtn');
    const clearBtn     = document.getElementById('clearBtn');
    const progressWrap = document.getElementById('progressWrap');
    const progressBar  = document.getElementById('progressBar');
    const progressText = document.getElementById('progressText');
    const spinner      = document.getElementById('spinner');

    let selectedFiles = [];

    function showSpinner() { spinner.classList.remove('hidden'); }
    function hideSpinner() { spinner.classList.add('hidden'); }

    function addFiles(fileListLike) {
      const incoming = Array.from(fileListLike);
      const valid = incoming.filter(f => /\.pdf$/i.test(f.name) || /\.zip$/i.test(f.name));
      selectedFiles = selectedFiles.concat(valid);
      renderFiles();
    }

    function renderFiles() {
      fileList.innerHTML = '';
      if (!selectedFiles.length) return;
      selectedFiles.forEach((file, idx) => {
        const tag = document.createElement('div');
        tag.className = 'bg-blue-100 text-blue-800 px-3 py-1 rounded-full text-sm flex items-center gap-2';
        tag.innerHTML = `${file.name} · ${(file.size/1024).toFixed(1)} KB 
          <button aria-label="Eliminar" class="ml-1 text-red-600 hover:text-red-800" data-idx="${idx}">✕</button>`;
        fileList.appendChild(tag);
      });
      fileList.querySelectorAll('button[data-idx]').forEach(btn => {
        btn.addEventListener('click', (e) => {
          const i = parseInt(e.currentTarget.getAttribute('data-idx'), 10);
          selectedFiles.splice(i, 1);
          renderFiles();
        });
      });
    }

    function clearAll() {
      selectedFiles = [];
      fileInput.value = '';
      fileList.innerHTML = '';
      statusBox.innerHTML = '';
      hideProgress();
    }

    function showProgress() {
      progressWrap.classList.remove('hidden');
      progressText.classList.remove('hidden');
      progressBar.style.width = '0%';
      progressText.textContent = '0%';
    }
    function updateProgress(percent) {
      const p = Math.max(0, Math.min(100, Math.round(percent)));
      progressBar.style.width = p + '%';
      progressText.textContent = p + '%';
    }
    function hideProgress() {
      progressWrap.classList.add('hidden');
      progressText.classList.add('hidden');
      progressBar.style.width = '0%';
      progressText.textContent = '0%';
    }

    dropzone.addEventListener('click', () => fileInput.click());
    browseBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      fileInput.click();
    });
    dropzone.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropzone.classList.add('border-blue-600');
    });
    dropzone.addEventListener('dragleave', () => dropzone.classList.remove('border-blue-600'));
    dropzone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropzone.classList.remove('border-blue-600');
      if (e.dataTransfer?.files?.length) addFiles(e.dataTransfer.files);
      fileInput.value = '';
    });
    fileInput.addEventListener('change', (e) => {
      if (e.target.files?.length) addFiles(e.target.files);
      fileInput.value = '';
    });
    clearBtn.addEventListener('click', clearAll);

    generateBtn.addEventListener('click', async () => {
      if (!selectedFiles.length) {
        statusBox.textContent = '⚠ Selecciona al menos un archivo (PDF o ZIP).';
        statusBox.className = 'text-red-500';
        return;
      }

      generateBtn.disabled = true;
      generateBtn.classList.add('opacity-60', 'cursor-not-allowed');
      statusBox.textContent = '';
      statusBox.className = 'text-gray-700';
      showSpinner();
      showProgress();

      const UPLOAD_WEIGHT   = 0.40;
      const PROCESS_WEIGHT  = 0.20;
      const DOWNLOAD_WEIGHT = 0.40;
      let processingTimer   = null;
      let processingProgress = 0;

      function setOverallProgress(p) {
        const pct = Math.max(0, Math.min(100, Math.round(p * 100)));
        updateProgress(pct);
      }

      const fd = new FormData();
      selectedFiles.forEach(f => fd.append('files', f));

      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/generate', true);
      xhr.responseType = 'blob';

      let downloadTotal = null;

      xhr.upload.onprogress = (e) => {
        if (!e.lengthComputable) return;
        const uploadPct = e.loaded / e.total;
        setOverallProgress(UPLOAD_WEIGHT * uploadPct);
      };

      xhr.upload.onload = () => {
        const start = UPLOAD_WEIGHT;
        const target = UPLOAD_WEIGHT + PROCESS_WEIGHT;
        processingProgress = start;
        if (processingTimer) clearInterval(processingTimer);
        processingTimer = setInterval(() => {
          processingProgress = Math.min(processingProgress + 0.01, target - 0.01);
          setOverallProgress(processingProgress);
        }, 120);
      };

      xhr.onprogress = (e) => {
        if (processingTimer) { clearInterval(processingTimer); processingTimer = null; }
        const h = xhr.getResponseHeader('Content-Length');
        if (h && downloadTotal === null) {
          const parsed = parseInt(h, 10);
          if (!isNaN(parsed) && parsed > 0) downloadTotal = parsed;
        }
        if (downloadTotal && e.loaded) {
          const downloadPct = e.loaded / downloadTotal;
          const overall = UPLOAD_WEIGHT + PROCESS_WEIGHT + DOWNLOAD_WEIGHT * downloadPct;
          setOverallProgress(overall);
        }
      };

      xhr.onload = () => {
        if (processingTimer) { clearInterval(processingTimer); processingTimer = null; }
        hideSpinner();
        generateBtn.disabled = false;
        generateBtn.classList.remove('opacity-60', 'cursor-not-allowed');

        if (xhr.status >= 200 && xhr.status < 300) {
          setOverallProgress(1);
          const blob = xhr.response;
          const fname = 'LabFluxHPH.docx';
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = fname;
          document.body.appendChild(a);
          a.click();
          a.remove();
          URL.revokeObjectURL(url);
          statusBox.textContent = '✅ Flujograma generado. Revisa tu descarga.';
          statusBox.className = 'text-green-600';
        } else {
          statusBox.textContent = '❌ Error de servidor.';
          statusBox.className = 'text-red-500';
        }
        setTimeout(hideProgress, 600);
      };

      xhr.onerror = () => {
        if (processingTimer) { clearInterval(processingTimer); processingTimer = null; }
        hideSpinner();
        generateBtn.disabled = false;
        generateBtn.classList.remove('opacity-60', 'cursor-not-allowed');
        statusBox.textContent = '❌ Error de red.';
        statusBox.className = 'text-red-500';
        hideProgress();
      };

      xhr.send(fd);
    });
  </script>
</body>
</html>
"""

@app.post("/generate")
async def generate(files: list[UploadFile] = File(...)):
    if not files:
        raise HTTPException(400, "Sube al menos un PDF.")

    pdf_bytes_list = extract_pdfs_from_uploads(files)
    if not pdf_bytes_list:
        raise HTTPException(400, "No se encontraron PDFs válidos.")

    all_rows = []
    for content in pdf_bytes_list:
        all_rows.extend(parse_pdf(content))

    ctx = build_context(all_rows)
    docx_bytes = render_docx(ctx)

    headers = {
        "Content-Disposition": 'attachment; filename="LabFluxHPH.docx"',
        "Content-Length": str(len(docx_bytes)),
        "Cache-Control": "no-cache",
    }

    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=headers,
    )


@app.post("/generate_json")
async def generate_json(files: list[UploadFile] = File(...), debug: int = 0):
    """
    Si debug=1 -> devuelve filas parseadas y contexto (sin DOCX).
    Si debug=0 -> devuelve el DOCX en base64 (uso normal).
    """
    if not files:
        raise HTTPException(400, "Sube al menos un PDF.")

    all_rows = []
    pdf_bytes_list = extract_pdfs_from_uploads(files)
    if not pdf_bytes_list:
        raise HTTPException(400, "No se encontraron PDFs válidos.")
    for content in pdf_bytes_list:
        all_rows.extend(parse_pdf(content))

    ctx = build_context(all_rows)
    if debug:
        # debug enriquecido con page_index y panel
        return {
            "debug": 1,
            "rows": all_rows,
            "ctx": ctx,
            "notes": "OK (solo debug, sin DOCX)"
        }

    docx_bytes = render_docx(ctx)
    data_b64 = base64.b64encode(docx_bytes).decode("ascii")
    return {
        "filename": "LabFluxHPH.docx",
        "mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "data_base64": data_b64,
        "notes": "OK (DOCX)"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)