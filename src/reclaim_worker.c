#define _DEFAULT_SOURCE
#include "common.h"
#include <fcntl.h>
#include <sys/stat.h>
#ifdef __linux__
#include <sys/vfs.h>
#include <linux/magic.h>
#endif

int main(int argc,char **argv) {
    if(argc<2) {fprintf(stderr,"usage: reclaim_worker EXPERIMENT_CGROUP_ROOT [--swappiness-max]\n");return 2;}
#ifndef __linux__
    (void)argv; fprintf(stderr,"memory.reclaim requires Linux\n");return 2;
#else
    int root=open(argv[1],O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
    struct statfs fs;
    if(root<0 || fstatfs(root,&fs) || (unsigned long)fs.f_type!=CGROUP2_SUPER_MAGIC) {
        fprintf(stderr,"target must be a real cgroup v2 directory\n");return 2;
    }
    int anon_only=flag(argc,argv,"--swappiness-max");
    setvbuf(stdout,NULL,_IOLBF,0);
    uint64_t previous=0; char line[256];
    while(fgets(line,sizeof(line),stdin)) {
        char id_text[32], donor[32], amount_text[32], extra;
        uint64_t id=0,amount=0; int error=EINVAL,valid=1;
        if(!strchr(line,'\n')) {int ch;while((ch=getchar())!='\n'&&ch!=EOF){} valid=0;}
        if(sscanf(line,"%31s %31s %31s %c",id_text,donor,amount_text,&extra)!=3)valid=0;
        if(valid) {
            for(size_t i=0;id_text[i];++i)if(id_text[i]<'0'||id_text[i]>'9')valid=0;
            for(size_t i=0;amount_text[i];++i)if(amount_text[i]<'0'||amount_text[i]>'9')valid=0;
            errno=0;id=strtoull(id_text,NULL,10);if(errno)valid=0;
            errno=0;amount=strtoull(amount_text,NULL,10);if(errno)valid=0;
            if(id<=previous || (strcmp(donor,"A") && strcmp(donor,"B")) || !amount ||
               amount>64*1024*1024 || amount%(uint64_t)sysconf(_SC_PAGESIZE))valid=0;
        }
        double start=seconds(CLOCK_MONOTONIC),cpu=seconds(CLOCK_PROCESS_CPUTIME_ID);
        if(valid) {
            previous=id;
            int leaf=openat(root,donor,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
            if(leaf<0)error=errno;
            else {
                int target=openat(leaf,"memory.reclaim",O_WRONLY|O_NOFOLLOW|O_CLOEXEC);
                if(target<0)error=errno;
                else {
                    char request[80];int len=snprintf(request,sizeof(request),"%" PRIu64 "%s",amount,anon_only?" swappiness=max":"");
                    ssize_t written=write(target,request,(size_t)len);
                    error=written==len?0:(written<0?errno:EIO);close(target);
                }
                close(leaf);
            }
        }
        double end=seconds(CLOCK_MONOTONIC),cost=seconds(CLOCK_PROCESS_CPUTIME_ID)-cpu;
        printf("{\"request_id\":%" PRIu64 ",\"start\":%.9f,\"end\":%.9f,\"wall_seconds\":%.9f,\"cpu_seconds\":%.9f,\"requested_bytes\":%" PRIu64 ",\"valid\":%s,\"errno\":%d,\"status\":\"%s\"}\n",
               id,start,end,end-start,cost,amount,valid?"true":"false",error,error?"error":"ok");
    }
    close(root);return 0;
#endif
}
