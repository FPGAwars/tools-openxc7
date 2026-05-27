#!/usr/bin/env python3

import subprocess
import shutil
import re
import stat
# import tarfile
from pathlib import Path
from datetime import datetime

import ansi


# ------ Nombre relativos de los directorios
# -- Base de la distribucion
DIST = "dist"
BIN = "bin"
LIBEXEC = "libexec"
LIB = "lib"

# -- TIPOS DE FICHERO
EJECUTABLE = 0
SHELL_SCRIPT = 1
PYTHON = 2


class ToolWrapper:

    # -- Cabecera del shell wrapper, comun a todos los wrappers
    BIN_WRAPPER = """\
#!/usr/bin/env bash\n
release_bindir="$(dirname "${BASH_SOURCE[0]}")"
release_bindir_abs="$(readlink -f "$release_bindir")"
release_topdir_abs="$(readlink -f "$release_bindir/..")"
export PATH="$release_bindir_abs:$PATH"
"""

    def __init__(self, bin_name: str):

        # -- Guardar el nombre del binario
        self.bin = bin_name

        # -- Shell: contenido del wrapper
        self.shell = self.BIN_WRAPPER

        # -- Guardar el path completo
        self.path = Path.cwd() / DIST / BIN / self.bin

    # -- Añadir trazas de depuracion
    def add_debug(self):
        self.shell += 'echo Bindir: ${release_bindir}\n'
        self.shell += 'echo Bindir_abs: ${release_bindir_abs}\n'
        self.shell += 'echo Topdir_abs: ${release_topdir_abs}\n'

    def add_exec_python(self):
        self.shell += 'export PYTHONEXECUTABLE='\
                      '"$release_bindir_abs/tabbypy3"\n'\
                      'exec "$release_bindir_abs/tabbypy3" '\
                      f'"$release_topdir_abs"/libexec/{self.bin} "$@"\n'

    def add_exec(self):
        self.shell += 'exec "$release_topdir_abs"/lib/ld-linux-x86-64.so.2 '\
                      '--inhibit-cache '\
                      '--inhibit-rpath "" '\
                      '--library-path "$release_topdir_abs"/lib '\
                      f'"$release_topdir_abs"/libexec/{self.bin} "$@"\n'

    # -- Devolver el path completo del wrapper
    def get_path(self) -> Path:
        return self.path

    def write_bin(self):

        # -- Obtener el path donde escribir el wrapper
        wrapper_file = self.path

        try:
            wrapper_file.write_text(self.shell, encoding="utf-8")

        except PermissionError:
            print(f"❌ Error: sin permisos '{self.bin}'.")
        except FileNotFoundError:
            print("❌ Directorio no existe")
        except Exception as e:
            print(f"❌ Error inesperado al escribir el archivo: {e}")

        # -- Dar permisos de ejecucion
        wrapper_file.chmod(wrapper_file.stat().st_mode | stat.S_IXUSR)


# ------------------------------------------------------------------
# -- Obtener las librerias dinámicas que son dependencias del
# -- fichero ejecutable indicado
# --
# -- ENTRADA:
# --   * binary: Nombre del fichero ejecutable
# --
# -- SALIDA:
# --   * Un diccionario con las librerias y sus paths
# ------------------------------------------------------------------
def get_dependencies(binary: str) -> dict:

    # -- Obtener la rutna del fichero binario
    ruta_binary = shutil.which(binary)

    # -- Obtener sus dependencias (Ejecutando el comando ldd)
    # -- Se obtiene la salida de texto en bruto
    deps_raw = subprocess.run(["ldd", str(ruta_binary)],
                              capture_output=True, text=True, check=True)

    # -- Diccionario para guardar las dependencias
    deps = {}

    # -- Recorrer la salida, linea a linea
    for linea in deps_raw.stdout.splitlines():
        linea = linea.strip()

        # Buscar el patrón: libname.so.X => /path/to/libname.so.X (0x0000...)
        match = re.search(r'(\S+)\s+=>\s+(\S+)', linea)
        if match:
            # -- Guardar la biblioteca y su path en el diccionario
            nombre_lib = match.group(1)
            ruta_lib = match.group(2)

            # -- Caso especial: ld-linux-x86-64.so.2
            # -- En nix viene con la ruta completa en el nombre. Lo truncamos
            # -- solo al nombre
            if "ld-linux-x86" in nombre_lib:
                nombre_lib = Path(nombre_lib).name
            deps[nombre_lib] = ruta_lib

        # Caso especial: El cargador dinámico (ej: /lib64/ld-linux-x86-64.so.2)
        # suele aparecer al final sin el símbolo '=>'
        elif "ld-linux" in linea or "ld.so" in linea:
            match_ld = re.search(r'(/[^ ]+)', linea)
            if match_ld:
                ruta_ld = match_ld.group(1)
                nombre_ld = ruta_ld.split("/")[-1]
                deps[nombre_ld] = ruta_ld

        # Caso especial: linux-vdso.so.1 (no tiene ruta física)
        elif "linux-vdso" in linea:
            match_vdso = re.search(r'(\S+)', linea)
            if match_vdso:
                deps[match_vdso.group(1)] = ""

    # -- Devolver el diccionario
    return deps


# ------------------------------------------------
# -- Copiar solo el fichero ejecutable indicado
# -- sin sus dependencias
# ------------------------------------------------
def copy_exec(binary: str, target_dir: str = LIBEXEC):
    # -- Obtener la ruta del ejecutable
    executable_path = Path(str(shutil.which(binary)))

    # -- Copiar el ejecutable  al directorio de la distribucion
    executable_target_dir = Path.cwd() / DIST / target_dir
    executable_target = executable_target_dir / binary

    # -- Marca para indicar el tipo de archivo
    mark = ""

    # -- Si no existe, copiarlo!
    if not executable_target.exists():
        shutil.copy(executable_path, executable_target)
        # -- Marca para indicar que se ha copiad
        mark = "✅"
    else:
        # -- Si existe, imprimir solo el nombre, sin copiar
        # -- Marca para indicar que ya estaba
        mark = "📌"

    # -- Imprimir nombre del ejecutable
    print(f"{ansi.GREEN}  ⚙️  Ejecutable: ",
          end='', flush=True)
    print(f"{ansi.DEFAULT}{mark}{binary}")


# ------------------------------------------------------
# -- Copiar el ejecutable indicado en la distribucion
# -- junto con TODAS sus librerias
# ------------------------------------------------------
def copy_with_deps(binary: str):

    # -- Copiar primero el ejecutable
    copy_exec(binary)

    # -- Leer las librerias dependencias del ejecutable
    executable_deps = get_dependencies(binary)

    # -- Directorio destino para las librerias
    libs_target_dir = Path.cwd() / DIST / LIB

    # -- Marca para indicar si el archivo se ha copiado (✅)
    # -- o bien no ha sido necesario porque ya estaba (📌)
    mark = ""

    # -- Copiar todas las dependencias de yosys
    for lib_name, libs_path in executable_deps.items():

        if libs_path != "":
            # -- Ruta completa del archivo en destino
            lib_target = libs_target_dir / Path(libs_path).name

            # -- Copiar la libreria si no existe ya...
            if not lib_target.exists():
                shutil.copy(libs_path, libs_target_dir)
                # -- Marca que indica que no existe
                mark = "✅"
            # -- Ya existe. No copiar, solo informar
            else:
                # -- Marca que indica que ya existe
                mark = "📌"

            # -- Imprimir nombre de la biblioteca
            print(f"{ansi.BLUE}  🧾 Lib: ",
                  end='', flush=True)
            print(f"{ansi.DEFAULT}{mark}{lib_name}")


# -----------------------------------------------------------
# -- Copiar todas las dependencias de python
# --
# -- store/tabbypy3 --> dist/bin
# -- nix-python/bin/python3.12 --> dist/libexec
# -- nix-python/lib/python3.12/* --> dist/lib/python3.12/
# -----------------------------------------------------------
def copy_python():

    # --- Copiar el wrapper (tabbypy3)
    origen = Path.cwd() / "store" / "tabbypy3"
    destino = Path.cwd() / DIST / BIN / "tabbypy3"
    if destino.exists():
        mark = "📌"
    else:
        shutil.copy(origen, destino)
        mark = "✅"
    print(f"➡️  Dep: {mark}bin/tabbypy3")

    # -- Copiar el ejecutable de python
    origen = Path(str(shutil.which("python3.12")))
    destino = Path.cwd() / DIST / LIBEXEC / "python3.12"
    if destino.exists():
        mark = "📌"
    else:
        shutil.copy(origen, destino)
        mark = "✅"
    print(f"➡️  Dep: {mark}libexec/{origen.name}")

    # -- Copiar el directorio completo de python
    origen = origen.parent.parent / "lib" / "python3.12"
    destino = Path.cwd() / DIST / LIB / "python3.12"
    if destino.exists():
        mark = "📌"
    else:
        shutil.copytree(origen, destino, dirs_exist_ok=True)
        mark = "✅"
    write_access(destino)
    print(f"➡️  Dep: {mark}lib/{origen.name}/")


# ----------------------------------------------------------------
# -- Localizar el path nix cuyo nombre contiene la cadena 'text'
# -- Devuelve el path completo
# --
# --  Ej.  nix_locate("python3.12-click-8.1.7") devuelve
# --       7b7509xv9aqdrayjf1fv5ialf4gbi5wd-python3.12-click-8.1.7
# -- Se descartan los paquetes que acaben en "-dev"
# ------------------------------------------------------------------
def nix_locate(text: str) -> Path:

    # -- Path de la tienda nix
    nix_store = Path("/nix/store")

    # -- Patron de busqueda
    patron = f"*{text}*"

    paths = [dir for dir in nix_store.glob(patron)
             if dir.is_dir() and not str(dir).endswith("-dev")]

    # -- Devolver la primera coincidencia
    return paths[0]


# -----------------------------------------------------------------------
# -- Copiar una biblioteca de python de nix a la distribucion
# -- El directorio del paquete copia a dist/lib/python3.12/site-packages
# --
# -- Ej. paquete click
# --    - Origen:
# --    /nix/store/xxx-python3.12-click/lib/python3.12/site-packages/
# --    - Desino:
# --      dist/lib/python3.12/site-packages
# -----------------------------------------------------------------------
def copy_python_dep(pyname: str, version: str, name: str = ""):

    if name == "":
        name = pyname

    # -- Nombre del paquete (nombre + version)
    pack_name = f"{pyname}" if version == "" else f"{pyname}-{version}"

    # -- Localizar la carpeta donde esta el paquete
    dir = nix_locate(f"python3.12-{pack_name}")

    # -- Directorio origen
    site_pack = dir / "lib" / "python3.12" / "site-packages"
    origen = site_pack / name

    # -- Directorio destino
    dst_site_pack = Path.cwd() / DIST / LIB / "python3.12" / "site-packages"
    destino = dst_site_pack / name

    # -- Dar permisos de escritura al directorio "site-packges"
    # -- de la distribucion
    write_access(dst_site_pack)

    mark = ""

    if destino.exists():
        mark = "📌"
    else:
        shutil.copytree(origen, destino, dirs_exist_ok=True)
        mark = "✅"

    print(f"➡️  Dep: {mark}{pack_name}")


# ------------------------------------
# -- Ejecutar el comando "file -b fich"
# -- Se devuelve la cadena procesada y
# -- en minusculas
# -------------------------------------
def cmd_file(fich: Path) -> str:

    # -- Ejecutar "file -b fich"
    resultado = subprocess.run(
        ['file', '-b', fich],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True
    )

    # -- Obtener la salida en crudo
    output_cmd = resultado.stdout.strip()

    # -- Pasarla a minusculas
    output_cmd = output_cmd.lower()

    # -- Devolver resultado
    return output_cmd


# ----------------------------------------------------
# -- Comprobar si el fichero es un ejecutable ELF
# -- Se hace llamando al comando "file"
# ----------------------------------------------------
def is_elf(fich: Path) -> bool:

    # -- Ejecutar comando "file -b fich"
    # -- Para saber el tipo de fichero
    output = cmd_file(fich)

    # -- Detectar el patron "elf"
    return "elf " in output


# -----------------------------------------------------
# -- Comprobar si es un programa PYTHON
# -----------------------------------------------------
def is_python_script(fich: Path) -> bool:

    # -- Ejecutar comando "file -b fich"
    # -- Para saber el tipo de fichero
    output = cmd_file(fich)

    # -- Detectar si es un script python
    return "python script" in output


# -----------------------------------------------------
# -- Comprobar si es un script shell
# -----------------------------------------------------
def is_shell_script(fich: Path) -> bool:

    # -- Ejecutar comando "file -b fich"
    # -- Para saber el tipo de fichero
    output = cmd_file(fich)

    # -- Detectar si es un script shell
    return ("bash script" in output) or ("bash -e script" in output)


# -----------------------------------------
# --  Añadir un shebang a un archivo python
# -----------------------------------------
def python_shebang_add(file_path: Path):

    try:
        # -- Leer archivo python
        contents = file_path.read_text(encoding="utf-8")

        # -- Shebang a añadir
        shebang = "#!/usr/bin/env python3\n"

        # -- Añadir shebang!
        contents = shebang + contents

        # -- Escribir nuevos contenidos
        file_path.write_text(contents, encoding="utf-8")
        # print(f"✔️ Shebang añadido con éxito a: {file_path}")

    except PermissionError:
        print(f"❌ Error: Sin permisos '{file_path}'.")
    except Exception as e:
        print(f"❌ Ocurrió un error inesperado: {e}")


# -----------------------------------------
# -- Añadir un shebang a un archivo bash
# -----------------------------------------
def bash_shebang_add(file_path: Path):

    try:
        # -- Leer archivo bash
        contents = file_path.read_text(encoding="utf-8")

        # -- Shebang a añadir
        shebang = "#!/usr/bin/env bash\n"

        # -- Añadir shebang!
        contents = shebang + contents

        # -- Escribir nuevos contenidos
        file_path.write_text(contents, encoding="utf-8")
        # print(f"✔️ Shebang añadido con éxito a: {file_path}")

    except PermissionError:
        print(f"❌ Error: Sin permisos '{file_path}'.")
    except Exception as e:
        print(f"❌ Ocurrió un error inesperado: {e}")


# -----------------------------------------
# -- Dar permisos de escritura al fichero
# -----------------------------------------
def write_access(file_path: Path):

    try:
        # Obtener los permisos
        permissions = file_path.stat().st_mode

        # Activar permisso de escritura
        permissions = permissions | stat.S_IWUSR

        # Aplicar los cambios
        file_path.chmod(permissions)
        # print(f"✔️ Permiso de escritura añadido a: {file_path}")

    except PermissionError:
        print("❌ Error: No tienes permiso")


# ------------------------------------------------------
# -- Cada herramienta tiene varios archivos ejecutables
# -- que se copian el libexec
# --
# -- Si el ejecutable es un ELF, se analizan todas sus
# -- librerias dinamicas de las que depende y se copian
# -- en lib
# --
# -- Si el ejecutable es un python, se añade una shebang
# -- y se copia en libexec
# --
# -- Si el ejecutable es un script shell, se añade shebang
# -- y se copia en bin
# --------------------------------------------------------
def run_fase1(name: str):
    print(ansi.YELLOW, end='')
    print("───────────────────────────────────")
    print("Fase 1: Ejecutables y bibliotecas")
    print(ansi.DEFAULT, end='')
    print()

    # -- Obtener la ruta del ejecutable
    executable_path = Path(str(shutil.which(name)))

    # -- Obtener su directorio
    executable_path_dir = executable_path.parent

    # -- Leer todos los ficheros que hay en ese directorio
    list_exec = [fich for fich in executable_path_dir.iterdir()
                 if fich.is_file()]

    # -- Recorrer todos los ficheros
    for fich in list_exec:

        # -- Informar del fichero actual
        print(f"🔵 {fich.name}", end='')

        # -- Es un EJECUTABLE
        if is_elf(fich):

            print("(ELF)")

            # -- Copiarlo a la distribucion
            # -- Junto a todas librerias
            copy_with_deps(fich.name)

        # -- Es un Script Python
        elif is_python_script(fich):
            print("(PYTHON)")

            # -- Copiarlo a la distribucion, sin mas
            copy_exec(fich.name)

            # -- Dar permisos de escritura al fichero python
            python_file_path = Path.cwd() / DIST / LIBEXEC / fich.name
            write_access(python_file_path)

            # -- Añadir un shee bang al comienzo
            python_shebang_add(python_file_path)

        # -- Es un script shell
        elif is_shell_script(fich):
            print("(SHELL)")

            # -- Copiarlo a la distribucion, sin mas
            copy_exec(fich.name, BIN)

            # -- Dar permisos de escritura al fichero bash
            bash_file_path = Path.cwd() / DIST / BIN / fich.name
            write_access(bash_file_path)

            # -- Añadir un shee bang al comienzo
            bash_shebang_add(bash_file_path)

        # -- Es otro tipo de archivo
        else:
            print("(UNKNOWN)")

        print()


# -----------------------------------------------------------------
# -- Procesado de herramient: Generacion de los wrappers
# --
# --  Cada fichero ejecutable (elf, python o shell) habita
# -- en el directorio libexec, y tiene otro ejecutable en bin
# -- con el mismo nombre, que es donde apunta el PATh y es por
# -- tanto el que se ejecuta: su wrapper
# --
# -- Lo que hace es llamar a verdadero ejecutable, pero
# -- estableciendo el directorio base donde se encuentran las
# -- librerias y datos, para que NO use los del sistema
# --
# -- Este metodo sería equivalente a tener bibliotecas estaticas
# -- pero usando librerias dinamicas
# ----------------------------------------------------------------
def run_fase2(name: str):
    print(ansi.YELLOW, end='')
    print("─────────────────────────────────────────────────────")
    print("Fase 2: Generacion de wrappers")
    print(ansi.DEFAULT, end='')
    print()

    # -- Obtener la ruta del ejecutable
    executable_path = Path(str(shutil.which(name)))

    # -- Obtener su directorio
    executable_path_dir = executable_path.parent

    # -- Leer todos los ficheros que hay en ese directorio
    list_exec = [fich for fich in executable_path_dir.iterdir()
                 if fich.is_file()]

    mark = ""
    info = ""

    # -- Recorrer todos los ficheros
    for fich in list_exec:

        # -- Es un EJECUTABLE
        if is_elf(fich):

            # -- Crear el wrapper
            wrapper = ToolWrapper(fich.name)
            # wrapper.add_debug()
            wrapper.add_exec()

            wrapper_path = wrapper.get_path()
            mark = "⬇️ " if wrapper_path.exists() else "✅"
            wrapper.write_bin()

            info = f"🔵 {mark}{fich.name}(ELF)"

        elif is_python_script(fich):

            # -- Crear el wrapper
            wrapper = ToolWrapper(fich.name)
            # wrapper.add_debug()
            wrapper.add_exec_python()

            wrapper_path = wrapper.get_path()
            mark = "⬇️ " if wrapper_path.exists() else "✅"
            wrapper.write_bin()
            info = f"🔵 {mark}{fich.name}(PYTHON)"

        elif is_shell_script(fich):
            info = f"❌ {fich.name}(SHELL)"

        else:
            info = f"❌ {fich.name}(UNKNOWN)"

        # -- Informar del fichero actual
        print(f"{info}")


# -----------------------------------------
# -- Copiar archivos especificos de yosys
# -----------------------------------------
def copy_tree(src: Path, dst: Path):

    mark = ""

    try:
        shutil.copytree(src, dst)  # dirs_exist_ok=True)
        write_access(dst)
        mark = "✅"

    except Exception:  # as e:
        mark = "📌"
        # print(f"❌ Error: {e}")

    finally:
        print(f"{mark} {dst.relative_to(Path.cwd())}")


# ------------------------------------------------
# -- Copiar el fichero del directorio fuente
# -- al destino, si es que no existe ya
# --
# -- Se devuelve una cadena con el nombre del fichero
# -- y una marca que indica si se ha copiado✅ o
# -- se mantiene la version anterior 📌
# ------------------------------------------------
def copy_file(src: Path, dst: Path) -> str:

    # mark = ""

    # -- Comprobar si el fichero ya existe en el
    # -- directorio destino
    if (dst / src.name).exists():

        # -- Ya existe, indicarlo
        mark = "📌"
    else:
        # -- No existe, copiarlo!
        try:
            shutil.copy2(src, dst)
        except Exception as e:
            print(f"❌ Error: {e}")
        mark = "✅"

    # -- Devolver cadena
    return (f"➡️  Dep: {mark}{src.name}")


def run_fase3_yosys():
    print(ansi.YELLOW, end='')
    print("───────────────────────────────────")
    print("Fase 3: Copiar datos de yosys")
    print()
    print(ansi.DEFAULT, end='')

    # ---- Obtener directorios
    # -- Directorio base de yosys
    base_dir = Path(str(shutil.which("yosys"))).parent.parent

    # -- Copiar /share/yosys
    origen = base_dir / "share" / "yosys"
    destino = Path.cwd() / DIST / "share" / "yosys"
    copy_tree(origen, destino)

    # -- Copiar las dependencias de python
    copy_python()

    # -- Copiar los paquetes especificos de python
    copy_python_dep("click", "8.1.7")


def run_fase3_nextpnr_xilinx():
    print(ansi.YELLOW, end='')
    print("───────────────────────────────────")
    print("Fase 3: Copiar datos de nextpnr-xilinx")
    print()
    print(ansi.DEFAULT, end='')

    # -- nextpnr-xilinx-0.8.2/share/nextpnr/external/prjxray-db/artix7/
    # -- ---> dist/share/nextpnr/external/prjxray-db/artix7/
    db_dir = "share/nextpnr/external/prjxray-db/artix7"
    base_src_dir = Path(str(shutil.which("nextpnr-xilinx"))).parent.parent
    origen = base_src_dir / db_dir

    destino = Path.cwd() / DIST / db_dir
    copy_tree(origen, destino)

    # -- nextpnr-xilinx-0.8.2/share/nextpnr/python --->
    # -- dist/share/nextpnr/python
    python_dir = "share/nextpnr/python"
    src = base_src_dir / python_dir
    dst = Path.cwd() / DIST / python_dir
    copy_tree(src, dst)

    # -- nextpnr-xilinx-0.8.2/share/nextpnr/constids.inc -->
    # -- dist/share/nextpnr
    src = base_src_dir / "share/nextpnr/constids.inc"
    dst = Path.cwd() / "dist/share/nextpnr"
    msg = copy_file(src, dst)
    print(msg)

    # -- nextpnr-xilinx-0.8.2/share/nextpnr/external/nextpnr-xilinx-meta/
    # --  artix7 -->
    # -- dist/share/nextpnr/external/nextpnr-xilinx-meta/artix7
    meta_dir = "share/nextpnr/external/nextpnr-xilinx-meta/artix7"
    src = base_src_dir / meta_dir
    dst = Path.cwd() / DIST / meta_dir
    copy_tree(src, dst)


def run_fase3_fasm():
    print(ansi.YELLOW, end='')
    print("───────────────────────────────────")
    print("Fase 3: Copiar datos de fasm")
    print()
    print(ansi.DEFAULT, end='')

    # --- Copiar fasm y sus dependencias
    copy_python_dep("fasm", "")
    copy_python_dep("textx", "4.0.1")

    # -- libantlr4
    dir = nix_locate("antl")
    src = dir / "lib"
    dst = Path.cwd() / "dist" / "lib"
    patron = "libantlr4-runtime.so.*"
    files = list(src.glob(patron))
    for file in files:
        msg = copy_file(file, dst)
        print(msg)

    # -- libuuid.so.1
    dir = nix_locate("linux-minimal-2.40.4-lib")
    src = dir / "lib" / "libuuid.so.1"
    dst = Path.cwd() / "dist" / "lib"
    msg = copy_file(src, dst)
    print(msg)


def run_fase3_prjxray():
    print(ansi.YELLOW, end='')
    print("───────────────────────────────────")
    print("Fase 3: Copiar datos de prjxray")
    print()
    print(ansi.DEFAULT, end='')

    # ---- Prjxray
    # {prjxray}/usr/share/python3/prjxray -->
    # ---> dist/lib/python3.12/site-packages/prjxray
    # -- Localizar la carpeta donde esta el paquete
    dir = nix_locate("prjxray")
    origen = dir / "usr" / "share" / "python3" / "prjxray"
    destino = Path.cwd() / DIST / LIB / "python3.12" \
        / "site-packages" / "prjxray"

    mark = ""
    if destino.exists():
        mark = "📌"
    else:
        shutil.copytree(origen, destino, dirs_exist_ok=True)
        mark = "✅"

    print(f"➡️  Dep: {mark}prjxray")

    # -- Paquetes python
    copy_python_dep("pyyaml", "6.0.1", "yaml")
    copy_python_dep("simplejson", "3.19.2")
    copy_python_dep("intervaltree", "3.1.0")
    copy_python_dep("sortedcontainers", "2.4.0")

    # -- DEBUG
    # dir = nix_locate("nextpnr-xilinx")
    # print(dir)


def procesar(name: str):
    print()
    print(f"{ansi.GREEN}────────────────────────────────────────")
    print(f"  {name.capitalize()}")
    print(f"{ansi.GREEN}────────────────────────────────────────")
    print(ansi.DEFAULT, end='', flush=True)
    # print()

    # -- Ejecutar fase 1: Copiar ejecutables y bibliotecas
    run_fase1(name)

    # -- Fase 2: Crear los wrappers para los ejecutables
    run_fase2(name)
    print()


# ----------------------------------------------------------
# -- Inicializar la distribucion
# --
# -- Crear la estructura de directorio inicial
# --
#    dist
#    |
#    +-- bin  --> Wrappers para los binarios
#    +-- libexec --> Ejecutables (elf, bash shell, python)
#    +-- lib     --> Bibliotecas dinamicas
#    +-- chipdb  --> binary database
# ----------------------------------------------------------
def distribution_init():
    # -- Directorio base de la distribucion
    base_dir = Path.cwd() / "dist"

    # -- Crear la estructura
    (base_dir / "bin").mkdir(parents=True, exist_ok=True)
    (base_dir / "lib").mkdir(parents=True, exist_ok=True)
    (base_dir / "libexec").mkdir(parents=True, exist_ok=True)
    (base_dir / "chipdb").mkdir(parents=True, exist_ok=True)


# -----------------------------------------------------------
# -- Obtener todos los bianrios, librerias y dependencias
# -- necesarios de TODAS las herramientas para realizar
# -- la sintesis
# -----------------------------------------------------------
def generar_binarios():
    # ------ Prcesar cada una de las herramientas
    # ------ Copiar los binarios, bibliotecas y datos
    # ------ a la distribucion
    # ------ Cada herramienta tiene un procesado que es comun
    # ------ para todas (procesar), y uno específico (run_fase3())

    # -- Yosys ya esta en oss-cad-suite, por lo que
    # -- no se incluye en openxc7
    # -- Se dejan las funciones para hacer pruebas en el
    # -- futuro
    # procesar("yosys")
    # run_fase3_yosys()

    # -- Copiar las dependencias de python
    print()
    print(f"{ansi.GREEN}────────────────────────────────────────")
    print("  PYTHON dependencies")
    print(f"{ansi.GREEN}────────────────────────────────────────")
    print(ansi.DEFAULT, end='', flush=True)
    copy_python()

    # -- Nextpnr-xilinx
    procesar("nextpnr-xilinx")
    run_fase3_nextpnr_xilinx()

    # --- fasm
    procesar("fasm")
    run_fase3_fasm()

    # -------- Herramienta prjxray
    procesar("fasm2frames")
    run_fase3_prjxray()
    print()


# --------------------------------------------
# -- Generar la base de datos
# -- Se genera el fichero:
# --- dist/chipdb/xc7a35tcpg236.bin
# --------------------------------------------
def generar_db():
    print()
    print(f"{ansi.GREEN}──────────────────────────────────")
    print("  GENERACION DE LA BASE DE DATOS")
    print(f"{ansi.GREEN}──────────────────────────────────")
    print(ansi.DEFAULT, end='', flush=True)
    print()

    # ------ Ejecutar comando 1
    bbaexport_cmd = Path.cwd() / "dist/share/nextpnr/python/bbaexport.py"
    part = "xc7a35tcpg236"
    fich_bba = Path.cwd() / f"dist/chipdb/{part}.bba"
    cmd = ["pypy3", str(bbaexport_cmd),
           "--device", f"{part}-1", "--bba", str(fich_bba)]
    cmd_str = " ".join(cmd)

    if not fich_bba.exists():
        print(f"➡️  Generando {fich_bba.name}")
        print(f"  ⚙️  {cmd_str}")
        bbaexport_raw = subprocess.run(cmd,
                                       capture_output=True,
                                       text=True,
                                       check=True)
        print(bbaexport_raw.stdout)
        print(f"🔵 ✅{fich_bba.name}")
    else:
        print(f"🔵 📌{fich_bba.name}")

    # ------ Comando 2
    fich_bin = Path.cwd() / f"dist/chipdb/{part}.bin"
    cmd = ["bbasm", "-l", str(fich_bba), str(fich_bin)]
    cmd_str = " ".join(cmd)

    if not fich_bin.exists():
        print()
        print(f"➡️  Generando {fich_bin.name}")
        print(f"  ⚙️  {cmd_str}")
        bbasm_raw = subprocess.run(cmd,
                                   capture_output=True,
                                   text=True,
                                   check=True)
        print(bbasm_raw.stdout)
        print(f"🔵 ✅{fich_bin.name}")
    else:
        print(f"🔵 📌{fich_bin.name}")

    # --- Eliminar fichero temporal .bba
    subprocess.run(["rm", fich_bba])
    # print(f"{ansi.GREEN}OK!")
    # print(f"{ansi.DEFAULT}")
    print()


# ------------------------------------------------------
# -- Configuraciones finales
# -- * Copiar el fichero environment en la raiz de la
# -- distribucion
# ------------------------------------------------------
def generar_env():
    # -- Configuraciones finales
    print()
    print(f"{ansi.GREEN}──────────────────────────────────")
    print("  CONFIGURACION FINAL")
    print(f"{ansi.GREEN}──────────────────────────────────")
    print(ansi.DEFAULT, end='', flush=True)
    print()

    # -- Incluir el fichero environment
    # -- config/environment --> dist
    src = Path.cwd() / "config/environment"
    dst = Path.cwd() / "dist"
    msg = copy_file(src, dst)
    print(msg)
    print()


# -----------------------------------
# -- Devolver la fecha actual en
# -- formato año-mes-dia
# --
# -- Ej. "20260526"
# ------------------------------------
def get_date() -> str:

    now = datetime.now()

    # -- Formato a utilizar
    # %Y = Año con 4 dígitos (ej. 2026)
    # %m = Mes con 2 dígitos (ej. 05)
    # %d = Día del mes con 2 dígitos (ej. 26)
    date = now.strftime("%Y%m%d")

    return date


# --------------------------------------------------
# -- Generar el fichero con la version, que se
# -- copia en la distribucion
# -- Devuelve el texto con la version
# --------------------------------------------------
def generar_version() -> str:
    print(f"{ansi.GREEN}──────────────────────────────────")
    print("  GENERANDO LA VERSION")
    print(f"{ansi.GREEN}──────────────────────────────────")
    print(ansi.DEFAULT, end='', flush=True)
    print()

    date = get_date()
    archivo_version = Path("dist/VERSION")
    archivo_version.write_text(date, encoding="utf-8")
    print(f"🏷️  Version: {date}")
    print(f"🔵 Fichero: ✅{archivo_version.name}")
    print()

    # -- Devolver cadena con la version
    return date


# ----------------------------------------------------
# -- Construir el fichero .tgz con la distribucion
# --
# -- tools-openxc7-linux-x64-version.tgz
# ----------------------------------------------------
def construir_tarball(version: str):

    # -- Generar tarball
    print(f"{ansi.GREEN}──────────────────────────────────")
    print("  GENERANDO TARBALL")
    print(f"{ansi.GREEN}──────────────────────────────────")
    print(ansi.DEFAULT, end='', flush=True)
    print()

    # -- Nombre del paquete
    tarball_name = Path(f"tools-openxc7-linux-x64-{date}.tgz")

    # -- Comprimir llamando a tar en la shell
    print(f"➡️  {tarball_name}")
    print("⏳ Comprimiendo...")
    comando = ["tar", "-czf", f"{tarball_name}",
               "--transform=s|^dist|tools-openxc7|", "dist/"]
    subprocess.run(comando,
                   check=True,
                   capture_output=True,
                   text=True)

    # -- Mostrar nombre del tarball al usuario
    print(f"🔵 ✅{tarball_name}")
    print()


# -----------------
#    MAIN
# -----------------
print(ansi.CLS, end='', flush=True)
print(f"{ansi.BLUE}", end='', flush=True)
print("─────────────────────────")
print("OPENXC7-PACK")
print("─────────────────────────")
print(ansi.DEFAULT, end='', flush=True)
print("Pack the toolchains binaries for Xilinx FPGAs...")


# -- Inicializar distribucion
distribution_init()

# -- Obtener binarios, bibliotecas y datos necesarios
generar_binarios()

# --- Generacion de la base de datos
# --- xc7a35tcpg236.bin
generar_db()

# -- Configuraciones finales
generar_env()

# -- Generar la version
date = generar_version()

# -- Generar el tarball
construir_tarball(date)
