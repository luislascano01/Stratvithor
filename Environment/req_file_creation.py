import yaml

# Load the YAML file.
with open("requirements_linux.yaml", "r") as f:
    env = yaml.safe_load(f)

dependencies = env.get("dependencies", [])
packages = []

for dep in dependencies:
    if isinstance(dep, str):
        # For conda dependencies, split on '=' and keep the package name.
        pkg = dep.split('=')[0]
        packages.append(pkg)
    elif isinstance(dep, dict) and "pip" in dep:
        # For pip dependencies, split on '==' and keep the package name.
        for pip_dep in dep["pip"]:
            pkg = pip_dep.split("==")[0]
            packages.append(pkg)

# Write out the package names to a requirements.txt file.
with open("requirements_linux.txt", "w") as f:
    for pkg in packages:
        f.write(pkg + "\n")
