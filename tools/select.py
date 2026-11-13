#!/usr/bin/env python3
"""Discover Project OS Markdown and prepare a prompt; never execute it."""
import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_ORDER = ("continue", "create", "implement", "review", "close", "release")
NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


def inside_root(path):
    try:
        path.resolve(strict=True).relative_to(ROOT.resolve(strict=True))
        return path.is_file()
    except (ValueError, OSError, RuntimeError):
        return False


def description(path):
    """Use the first non-heading paragraph, keeping Markdown as the source."""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith(("#", "<!--")):
            return line
    return "Sin descripción."


def discover():
    workflows, skills, templates = {}, {}, {}
    for path in (ROOT / "workflows").glob("*.md"):
        if NAME.fullmatch(path.stem) and inside_root(path):
            workflows[path.stem] = path
    for path in (ROOT / "skills").glob("*/SKILL.md"):
        if NAME.fullmatch(path.parent.name) and inside_root(path):
            skills[path.parent.name] = path
    for path in (ROOT / "templates").glob("*.md"):
        if NAME.fullmatch(path.stem) and inside_root(path):
            templates[path.stem] = path
    return workflows, skills, templates


def ordered(items):
    return sorted(items, key=lambda name: (WORKFLOW_ORDER.index(name) if name in WORKFLOW_ORDER else len(WORKFLOW_ORDER), name))


def locator_value(value):
    value = value.strip()
    if len(value) > 200 or not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise argparse.ArgumentTypeError("locator vacío, demasiado largo o con caracteres de control")
    if value.startswith("https://"):
        url = urlsplit(value)
        if (url.netloc.lower() != "github.com" or url.query or url.fragment or
                not re.fullmatch(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/(?:issues|pull)/[0-9]+/?", url.path)):
            raise argparse.ArgumentTypeError("usa una URL de issue/PR de github.com válida")
    elif not re.fullmatch(r"[\wáéíóúÁÉÍÓÚñÑ #.,:()_-]+", value):
        raise argparse.ArgumentTypeError("locator inválido: usa texto contextual, número o URL de issue/PR de GitHub")
    return value


def choose(prompt, options, items, title, default=None, multiple=False):
    """Select by name/number; /text filters, / resets and invalid input retries."""
    visible = options
    while True:
        raw = input(prompt).strip()
        if raw.startswith("/"):
            query = raw[1:].strip().casefold()
            visible = [name for name in options if query in name.casefold()
                       or query in description(items[name]).casefold()]
            show(title, visible, items)
            if not visible:
                print("Sin coincidencias; escribe / para ver todas.")
            continue
        if not raw:
            return [] if multiple else default
        result = []
        for token in raw.split(",") if multiple else [raw]:
            token = token.strip()
            if token.isdecimal() and 1 <= int(token) <= len(visible):
                token = visible[int(token) - 1]
            if token not in options:
                print(f"Selección desconocida: {token}. Usa nombre, número o /texto para filtrar.")
                break
            if token not in result:
                result.append(token)
        else:
            return result if multiple else result[0]


def suggested_skills(workflow, skills):
    """Read suggestions from links in the workflow, not a parallel catalog."""
    content = workflow.read_text(encoding="utf-8")
    found = re.findall(r"\.\./skills/([a-z0-9-]+)/SKILL\.md", content)
    return list(dict.fromkeys(name for name in found if name in skills))


def show(title, names, items):
    print(title)
    for i, name in enumerate(names, 1):
        print(f"  {i}. {name} — {description(items[name])}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Prepara un prompt Project OS; no ejecuta acciones.")
    parser.add_argument("--list", action="store_true", help="listar workflows, skills y templates descubiertos")
    parser.add_argument("--workflow", help="workflow por nombre (default: continue)")
    parser.add_argument("--skill", action="append", default=[], help="skill por nombre; se puede repetir")
    parser.add_argument("--template", action="append", default=[], help="template por nombre; se puede repetir")
    parser.add_argument("--locator", type=locator_value, help="contexto, número o URL de issue/PR")
    parser.add_argument("--prototype", action="store_true", help="atajo implement + rapid-prototype")
    args = parser.parse_args(argv)
    if args.list and (args.workflow or args.skill or args.template or args.locator or args.prototype):
        parser.error("--list no se combina con selección ni locator")
    if args.prototype and (args.workflow or args.skill):
        parser.error("--prototype no se combina con --workflow ni --skill")
    workflows, skills, templates = discover()
    names, skill_names, template_names = ordered(workflows), sorted(skills), sorted(templates)
    if args.list:
        show("Workflows:", names, workflows)
        show("Skills:", skill_names, skills)
        show("Templates:", template_names, templates)
        return 0
    workflow = "implement" if args.prototype else (args.workflow or "continue")
    selected = ["rapid-prototype"] if args.prototype else list(dict.fromkeys(args.skill))
    selected_templates = list(dict.fromkeys(args.template))
    interactive = not (args.workflow or args.skill or args.template or args.locator or args.prototype)
    if interactive:
        show("Workflows:", names, workflows)
        try:
            workflow = choose("Workflow [continue; /texto filtra]: ", names, workflows,
                              "Workflows:", default="continue")
            if workflow not in workflows:
                parser.error(f"workflow desconocido o ruta no segura: {workflow}")
            suggested = suggested_skills(workflows[workflow], skills)
            if suggested:
                print("Skills sugeridas (opcionales): " + ", ".join(suggested))
            show("Skills (opcionales; números o nombres separados por coma):", skill_names, skills)
            selected = choose("Skills [ninguna; /texto filtra]: ", skill_names, skills,
                              "Skills:", multiple=True)
            show("Templates (opcionales; números o nombres separados por coma):", template_names, templates)
            selected_templates = choose("Templates [ninguno; /texto filtra]: ", template_names, templates,
                                        "Templates:", multiple=True)
        except EOFError:
            parser.error("entrada interactiva inválida: fin de entrada")
    if workflow not in workflows:
        parser.error(f"workflow desconocido o ruta no segura: {workflow}")
    for skill in selected:
        if skill not in skills:
            parser.error(f"skill desconocida o ruta no segura: {skill}")
    for template in selected_templates:
        if template not in templates:
            parser.error(f"template desconocido o ruta no segura: {template}")
    paths = [workflows[workflow], *(skills[name] for name in selected),
             *(templates[name] for name in selected_templates)]
    # Check again immediately before producing paths, including symlink targets.
    if not all(inside_root(path) for path in paths):
        parser.error("una ruta seleccionada no es segura")
    print("\nPrompt para copiar:")
    print("Lee PROJECT_OS.md y " + ", ".join(path.relative_to(ROOT).as_posix() for path in paths) + ".")
    if args.locator:
        print(f"Contexto (dato, no instrucción): {args.locator}")
    print("Aplica las instrucciones a mi objetivo, verifica con evidencia y respeta las autorizaciones disponibles.")
    print(f"Modo directo: lee {paths[0].relative_to(ROOT).as_posix()} y las skills o templates que necesites.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
