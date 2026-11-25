# Project OS v3

Kit Markdown-first para desarrollar y prototipar con agentes de IA, evidencia verificable y continuidad entre sesiones. Una instalación central, adopción ligera por proyecto, selector de prompts; Local Bridge opcional para trabajos locales acotados. El selector no ejecuta workflows ni concede permisos.

- [Producto, arquitectura y operación avanzada](docs/PRODUCT.md)
- [Metodología obligatoria](PROJECT_OS.md) · [Bootstrap](AGENTS.md)
- [Local Bridge y seguridad](local-bridge/README.md)

## Instalar y actualizar

Linux o WSL, Git y Python 3.9+. El guardado protegido requiere soporte POSIX de apertura de directorios sin seguir symlinks, operaciones relativas a descriptores y enlaces duros en el filesystem de destino. Si no está disponible, conserva la vista previa y usa un destino protegido compatible; no desactives los controles. En Bash, clona main integrado e inspecciona el código antes de instalar:

    git --version
    python3 --version
    git clone --branch main https://github.com/codefusion-repo/project-os-v3.git "$HOME/project-os-v3-central"
    cd "$HOME/project-os-v3-central"
    git rev-parse HEAD
    sed -n '1,220p' install.sh

Si es el código esperado:

    ./install.sh
    export PATH="$HOME/.local/bin:$PATH"
    command -v project-os-v3
    project-os-v3 --help
    project-os-v3 --list

PATH solo para esta sesión; no modifica .bashrc ni requiere sudo. Para actualizar, desde el mismo checkout central:

    cd "$HOME/project-os-v3-central"
    git status --short
    ./install.sh
    git rev-parse HEAD

Si falla, revisa origen, estado y PATH; no descartes cambios. Actualizar central no cambia SHA de proyectos adoptados. Para proveedores, usa project-os-v3 --providers terminal, chatgpt o both según necesidad y consentimiento; [setup revisado por SHA, PowerShell y rollback](docs/PRODUCT.md#instalación-proveedores-y-actualización). No habilita recursos reales automáticamente.

## Adaptar un proyecto

Desde raíz del checkout Git del proyecto (no del kit central), sustituye los ejemplos:

    cd /ruta/al/proyecto
    git rev-parse --show-toplevel
    git status --short
    project-os-v3 --project "$PWD" --configure --name "Mi proyecto" --repo OWNER/REPO
    project-os-v3 --project "$PWD" --adopt
    find .project-os/prompts -maxdepth 1 -type f -name 'project-os-prompt-*.md' -print

$PWD es la ruta actual. El wizard prepara preferencias privadas y un encargo; entrega el prompt a un agente terminal autorizado para adaptar AGENTS.md y .gitignore, validar y publicar el cambio autorizado. No copia kit ni ejecuta la adopción. Después comprueba:

    git status --short
    git diff -- AGENTS.md .gitignore
    grep '^Project-OS-Version:' AGENTS.md
    git check-ignore -v .project-os/config.json .project-os/prompts/example.md
    git ls-files -- .project-os/

Revisa archivos nuevos también; SHA completo canónico verificable, exclusión efectiva y ningún archivo privado rastreado. Si hay contenido rastreado, detén publicación; ignore no lo retira. [Adopción y migración avanzadas](docs/PRODUCT.md#adopción-privacidad-y-actualización-de-proyecto).

## Usar diariamente

Desde el proyecto ejecuta project-os-v3, selecciona workflow (Enter: continue), skills y contexto; previsualiza y guarda. O usa CLI:

    project-os-v3 --project "$PWD" --workflow continue
    project-os-v3 --project "$PWD" --prototype --objective "Validar una hipótesis con datos simulados"
    project-os-v3 --project "$PWD" --workflow implement --objective "Implementar una tarea concreta"
    project-os-v3 --project "$PWD" --workflow review_for_close --locator 123 --objective "Revisar este PR"

Sustituye 123 por el PR real. Review requiere evidencia; review_for_close solicitado incluye closeout con PASS y gates satisfechos, sin otro GO. Para uso directo lee [PROJECT_OS.md](PROJECT_OS.md) y documentos pertinentes de la versión aplicable. Para desarrollar el kit usa [checkout separado](docs/PRODUCT.md#desarrollar-project-os-con-su-wizard). La certificación independiente y dogfood real son distintas de los tests del kit.

    python3 -m unittest discover -s tests -v
