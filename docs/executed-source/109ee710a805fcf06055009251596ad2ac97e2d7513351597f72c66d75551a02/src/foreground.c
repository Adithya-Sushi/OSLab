#define _DEFAULT_SOURCE
#include "common.h"
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/mman.h>
#include <sys/time.h>

static volatile sig_atomic_t stopping=0;
static void stop_signal(int sig) { (void)sig; stopping=1; }
int main(int argc,char **argv) {
    const char *path=argument(argc,argv,"--socket","/tmp/oslab.sock");
    size_t mib=number(argument(argc,argv,"--mib","128"));
    size_t touches=number(argument(argc,argv,"--touches","256"));
    if (!mib || mib>4096 || !touches || touches>1048576 || strlen(path)>=sizeof(((struct sockaddr_un*)0)->sun_path)) return 2;
    size_t n=mib*1024*1024/8;
    uint64_t *memory=mmap(NULL,n*8,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
    if (memory==MAP_FAILED) { perror("mmap"); return 2; }
    const uint64_t salt=UINT64_C(0x517cc1b727220a95);
    for(size_t i=0;i<n;++i) memory[i]=(uint64_t)i^salt;
    int server=socket(AF_UNIX,SOCK_STREAM,0);
    if(server<0) {perror("socket");return 2;}
    struct sockaddr_un address; memset(&address,0,sizeof(address));
    address.sun_family=AF_UNIX; strcpy(address.sun_path,path);
    /* The runner uses a unique socket; never unlink a pre-existing endpoint. */
    if(bind(server,(struct sockaddr*)&address,sizeof(address)) || listen(server,128)) {perror("bind/listen");return 2;}
    struct sigaction sa; memset(&sa,0,sizeof(sa)); sa.sa_handler=stop_signal;
    sigaction(SIGTERM,&sa,NULL); sigaction(SIGINT,&sa,NULL); signal(SIGPIPE,SIG_IGN);
    setvbuf(stdout,NULL,_IOLBF,0);
    printf("{\"event\":\"ready\",\"t\":%.9f,\"bytes\":%zu}\n",seconds(CLOCK_MONOTONIC),n*8);
    while(!stopping) {
        int client=accept(server,NULL,NULL);
        if(client<0) {if(errno==EINTR)continue;perror("accept");break;}
        struct timeval timeout={2,0}; setsockopt(client,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout));
        char input[128], output[128]; size_t used=0;
        while(used+1<sizeof(input)) {
            ssize_t count=read(client,input+used,1);
            if(count!=1) break;
            if(input[used++]=='\n') break;
        }
        input[used]='\0'; uint64_t id,key; char extra;
        if(sscanf(input,"%" SCNu64 " %" SCNu64 " %c",&id,&key,&extra)==2) {
            uint64_t result=0;
            for(size_t j=0;j<touches;++j) {
                size_t index=(size_t)((key+j*UINT64_C(4099))%n);
                result+=((volatile uint64_t*)memory)[index]^key;
            }
            int length=snprintf(output,sizeof(output),"%" PRIu64 " %" PRIu64 "\n",id,result);
            size_t sent=0;
            while(sent<(size_t)length) {
                ssize_t count=write(client,output+sent,(size_t)length-sent);
                if(count<=0) break;
                sent+=(size_t)count;
            }
        }
        close(client);
    }
    close(server); unlink(path); munmap(memory,n*8); return 0;
}
