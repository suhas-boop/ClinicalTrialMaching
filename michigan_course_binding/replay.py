"""Start an isolated HAPI R4 instance and run the synthetic suite (Python 3.12+, Java 11)."""
import argparse
import hashlib
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener, urlopen

ROOT = Path(__file__).resolve().parent
MAVEN = "https://repo.maven.apache.org/maven2/"
ASSETS = {
    "starter.war": ("ca/uhn/hapi/fhir/hapi-fhir-jpaserver-starter/5.4.0/hapi-fhir-jpaserver-starter-5.4.0.war",
                    "2b44cb4ad66f9c9774fbf52e360f01d57944ae525306adab1fc4e292dce145b8"),
    "tomcat.tar.gz": ("org/apache/tomcat/tomcat/9.0.110/tomcat-9.0.110.tar.gz",
                      "94393eb928ed01d58008af6925660d7a7d372661de5cef8d63c66a1aaa289618"),
    "snakeyaml-1.33.jar": ("org/yaml/snakeyaml/1.33/snakeyaml-1.33.jar",
                           "11ff459788f0a2d781f56a4a86d7e69202cebacd0273d5269c4ae9f02f3fd8f0"),
}


def start(work, args):
    cache = args.cache or work
    cache.mkdir(parents=True, exist_ok=True)
    for name, (url, digest) in ASSETS.items():
        target = cache / name
        if not target.exists():
            with urlopen(MAVEN + url, timeout=90) as response, target.open("wb") as out:
                shutil.copyfileobj(response, out)
        with target.open("rb") as saved:
            if hashlib.file_digest(saved, "sha256").hexdigest() != digest:
                raise ValueError(f"Checksum mismatch in {target}")
    with tarfile.open(cache / "tomcat.tar.gz") as archive:
        archive.extractall(work, filter="data")
    tomcat = next(p.parent.parent for p in work.glob("*/bin/catalina.sh"))
    appbase = work / "webapps"
    app = appbase / "ROOT"
    with zipfile.ZipFile(cache / "starter.war") as archive:
        archive.extractall(app)
    # The released 5.4.0 WAR needs the YAML dependency and this indentation repair.
    shutil.copy(cache / "snakeyaml-1.33.jar", app / "WEB-INF/lib")
    config = app / "WEB-INF/classes/application.yaml"
    config.write_text(config.read_text().replace("     cors:", "    cors:"))
    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    conf = tomcat / "conf/server.xml"
    tree = ET.parse(conf)
    tree.getroot().set("port", "-1")
    connector = tree.find(".//Connector")
    connector.set("address", "127.0.0.1")
    connector.set("port", str(port))
    tree.find(".//Host").set("appBase", str(appbase))
    tree.write(conf)
    opts = "-Xmx1300m -Dspring.datasource.url=jdbc:h2:mem:pocketmd -Dhapi.fhir.reuse_cached_search_results_millis=0"
    env = dict(os.environ, JAVA_HOME=str(args.java_home), CATALINA_HOME=str(tomcat), JAVA_OPTS=opts)
    base = f"http://127.0.0.1:{port}/fhir"
    opener = build_opener(ProxyHandler({}))
    with (work / "server.log").open("w") as log:
        process = subprocess.Popen([str(tomcat / "bin/catalina.sh"), "run"], cwd=work,
                                   env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            for _ in range(120):
                if process.poll() is not None:
                    break
                try:
                    with opener.open(base + "/metadata?_format=json", timeout=2) as response:
                        if response.status == 200:
                            subprocess.run([sys.executable, str(ROOT / "run.py"), base,
                                            "--out", str(args.out)], check=True)
                            return
                except (URLError, TimeoutError, ConnectionError):
                    pass
                time.sleep(1)
            raise RuntimeError((work / "server.log").read_text()[-3500:])
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--java-home", default=os.environ.get("JAVA_HOME"))
    cli.add_argument("--cache", type=Path, help="Optional directory for verified dependency downloads")
    cli.add_argument("--out", type=Path, default=ROOT / "replay-results.json")
    args = cli.parse_args()
    if not args.java_home or not (Path(args.java_home) / "bin/java").is_file():
        cli.error("Set JAVA_HOME or pass --java-home for a Java 11 installation.")
    args.java_home = Path(args.java_home).resolve()
    args.out = args.out.resolve()
    with tempfile.TemporaryDirectory(prefix="pocketmd-r4-") as temp:
        start(Path(temp), args)
