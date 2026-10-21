from dataclasses import dataclass

@dataclass
class Budget:
    byte_cap:int=256*1024*1024
    wall_cap:float=2.0
    requested:int=0
    wall:float=0.0
    cpu:float=0.0
    in_flight:bool=False
    stopped:bool=False

    def admit(self,amount):
        if self.in_flight or self.stopped or amount<=0 or self.requested+amount>self.byte_cap or self.wall>=self.wall_cap:
            return False
        self.requested+=amount;self.in_flight=True
        return True

    def complete(self,result):
        if not self.in_flight:raise RuntimeError("completion without admission")
        self.wall+=result["wall_seconds"];self.cpu+=result["cpu_seconds"];self.in_flight=False
        if self.wall>=self.wall_cap:self.stopped=True

    def overdue(self):
        self.stopped=True

    def snapshot(self):
        return dict(self.__dict__,wall_overshoot=max(0,self.wall-self.wall_cap))
