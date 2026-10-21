"""Unpressured service capacity check; separate from memory-benefit experiments."""
import argparse
import json
from pathlib import Path
import socket
import tempfile
import time
from .common import BIN,ROOT,write_json,host_information
from .launch import Worker
from .load_generator import expected_result,percentile

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--touches",type=int,default=65536)
    parser.add_argument("--requests",type=int,default=1000)
    args=parser.parse_args()
    output=ROOT/"results/derived/calibration";output.mkdir(exist_ok=True,parents=True)
    endpoint=Path(tempfile.gettempdir())/f"oslab-capacity-{time.time_ns()}.sock"
    worker=Worker("capacity-service",[str(BIN/"foreground"),"--socket",str(endpoint),"--mib","128","--touches",str(args.touches)],output)
    worker.await_ready()
    expected=[expected_result(i+1,128,args.touches) for i in range(args.requests+100)]
    latencies=[];raw=[]
    try:
        started=None
        for i in range(args.requests+100):
            if i==100:started=time.monotonic()
            begin=time.monotonic()
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
                client.settimeout(2);client.connect(str(endpoint));client.sendall(f"{i} {i+1}\n".encode())
                reply=client.makefile("rb").readline()
            finish=time.monotonic()
            response_id,result=map(int,reply.split())
            if response_id!=i or result!=expected[i]:raise RuntimeError("foreground checksum mismatch")
            if i>=100:
                latencies.append(finish-begin);raw.append({"id":i,"start":begin,"end":finish})
        elapsed=time.monotonic()-started
        rate=args.requests/elapsed
        report={"kind":"unpressured_sequential_client_capacity","environment":host_information(),
                "requests":args.requests,"working_set_mib":128,"touches":args.touches,
                "elapsed_seconds":elapsed,"requests_per_second":rate,
                "recommended_initial_offered_rate":int(.4*rate),"p99_seconds":percentile(latencies,.99),
                "limitations":"Single closed-loop client includes connection and client overhead; an initial capacity estimate, not a service maximum."}
        write_json(output/"capacity.json",report)
        write_json(output/"capacity-requests.json",raw)
        print(json.dumps(report))
    finally:worker.stop()

if __name__=="__main__":main()
