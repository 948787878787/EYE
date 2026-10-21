"""Download the Taiwan intersection photos (Roboflow Universe lawrence-yeh/traffic-sign-mos2b-zhep9, CC BY 4.0) that
the EYE labels refer to. Needs a free Roboflow account: put your API key in the ROBOFLOW_API_KEY environment variable
(never in this file).
Usage: pip install roboflow
       ROBOFLOW_API_KEY=... python dataset/script/download_roboflow.py [--out data/roboflow_v1] [--version 1]
"""
import argparse
import os
import sys

WORKSPACE = "lawrence-yeh"
PROJECT = "traffic-sign-mos2b-zhep9"
FORMAT = "yolov11"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=os.path.join("data", "roboflow_v1"))
    ap.add_argument("--version", type=int, default=1, help="dataset version the labels were made on (1)")
    a = ap.parse_args(argv)
    key = os.environ.get("ROBOFLOW_API_KEY")
    if not key:
        sys.exit("set ROBOFLOW_API_KEY (Roboflow -> Settings -> API Keys)")
    try:
        from roboflow import Roboflow
    except ImportError:
        sys.exit("pip install roboflow")
    project = Roboflow(api_key=key).workspace(WORKSPACE).project(PROJECT)
    project.version(a.version).download(FORMAT, location=a.out)
    print(f"downloaded to {a.out}")


if __name__ == "__main__":
    main()
