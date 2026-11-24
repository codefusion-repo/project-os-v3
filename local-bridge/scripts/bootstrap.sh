# Shared acquisition of the reviewed official pip wheel. Source only from the
# reviewed Git tree; callers supply fresh private wheel/home directories.
bootstrap_install() {
  local python="$1" wheels="$2" source_dir="$3" home="$4" wheel
  wheel="$wheels/pip-26.3-py3-none-any.whl"
  env -i PATH=/usr/bin:/bin HOME="$home" LC_ALL=C curl --disable --fail --silent --show-error --proto '=https' --noproxy '*' --max-time 120 --max-filesize 5000000 -o "$wheel" 'https://files.pythonhosted.org/packages/07/25/ee8c38ae72d66b844ce8eb9711ba905dba21ca1a8a0c960057c41cd23337/pip-26.3-py3-none-any.whl'
  "$python" -I "$source_dir/scripts/bootstrap_verify.py" "$wheel" "$source_dir/requirements-bootstrap.lock"
  env -i PATH=/usr/bin:/bin HOME="$home" LC_ALL=C PIP_CONFIG_FILE=/dev/null "$python" -I -c 'import runpy,sys; sys.path.insert(0,sys.argv.pop(1)); runpy.run_module("pip",run_name="__main__")' "$wheel" --isolated --disable-pip-version-check --no-input --no-cache-dir install --no-index --find-links "$wheels" --only-binary=:all: --require-hashes --no-deps -r "$source_dir/requirements-bootstrap.lock"
}
