#define _DEFAULT_SOURCE
#include "common.h"
#include <sys/mman.h>

static volatile sig_atomic_t stopping = 0;
static void stop_signal(int sig) { (void)sig; stopping = 1; }
static uint64_t checksum(const unsigned char *p, size_t size) {
    uint64_t h = UINT64_C(1469598103934665603);
    for (size_t i=0; i<size; ++i) h = (h ^ p[i]) * UINT64_C(1099511628211);
    return h;
}
int main(int argc, char **argv) {
    size_t mib = number(argument(argc,argv,"--mib","512"));
    size_t hot_mib = number(argument(argc,argv,"--hot-mib","32"));
    size_t reuse_mib = number(argument(argc,argv,"--reuse-mib","512"));
    size_t work_pages = number(argument(argc,argv,"--pages-per-tick","32"));
    uint64_t seed = number(argument(argc,argv,"--seed","1"));
    double duration = real_number(argument(argc,argv,"--duration","90"));
    double reuse_after = real_number(argument(argc,argv,"--reuse-after","999999"));
    double tick = real_number(argument(argc,argv,"--tick-seconds","0.01"));
    size_t extra_mib = number(argument(argc,argv,"--extra-mib","0"));
    double allocate_after = real_number(argument(argc,argv,"--allocate-after","999999"));
    double release_after = real_number(argument(argc,argv,"--release-after","999999"));
    const char *pattern = argument(argc,argv,"--pattern","structured");
    if (!mib || mib>4096 || !hot_mib || hot_mib>mib || reuse_mib>mib || !reuse_mib ||
        !work_pages || work_pages>1048576 || tick<0.001 || duration<=0 ||
        extra_mib>512 || (extra_mib && release_after<=allocate_after) ||
        (strcmp(pattern,"structured") && strcmp(pattern,"random"))) {
        fprintf(stderr,"invalid donor configuration\n"); return 2;
    }
    size_t size = mib*1024*1024, page = (size_t)sysconf(_SC_PAGESIZE);
    unsigned char *memory = mmap(NULL,size,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
    if (memory == MAP_FAILED) { perror("mmap"); return 2; }
#ifdef MADV_NOHUGEPAGE
    if (madvise(memory,size,MADV_NOHUGEPAGE)) { perror("madvise NOHUGEPAGE"); return 2; }
#endif
    /* Structured pages contain a changing, non-uniform 64-byte motif. Random
       pages use distinct 64-bit words. Both patterns instantiate every page. */
    uint64_t *words = (uint64_t*)memory;
    for (size_t i=0; i<size/8; ++i) {
        uint64_t index = !strcmp(pattern,"structured") ? ((i*8/page)*8 + i%8) : i;
        words[i] = mix64(seed ^ index);
    }
    uint64_t initial = checksum(memory,size), units=0, result=0;
    signal(SIGTERM,stop_signal); signal(SIGINT,stop_signal);
    setvbuf(stdout,NULL,_IOLBF,0);
    printf("{\"event\":\"ready\",\"t\":%.9f,\"bytes\":%zu,\"checksum\":\"%016" PRIx64 "\"}\n",
           seconds(CLOCK_MONOTONIC),size,initial);
    double epoch = seconds(CLOCK_MONOTONIC);
    if (flag(argc,argv,"--wait-start")) {
        char line[128];
        if (!fgets(line,sizeof(line),stdin) || sscanf(line,"START %lf",&epoch)!=1) return 2;
    }
    pause_until(epoch);
    double next=epoch, last=epoch; int phase=0;
    unsigned char *extra_memory=NULL; int allocated=0,extra_ok=1; uint64_t extra_checksum=0;
    while (!stopping && seconds(CLOCK_MONOTONIC)-epoch < duration) {
        double now = seconds(CLOCK_MONOTONIC);
        if(extra_mib && !allocated && now-epoch>=allocate_after) {
            extra_memory=mmap(NULL,extra_mib*1024*1024,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
            if(extra_memory==MAP_FAILED){perror("extra mmap");return 2;}
            uint64_t *extra_words=(uint64_t*)extra_memory;
            for(size_t i=0;i<extra_mib*1024*1024/8;++i)extra_words[i]=mix64(seed+i);
            extra_checksum=checksum(extra_memory,extra_mib*1024*1024);allocated=1;
            printf("{\"event\":\"extra_allocated\",\"t\":%.9f,\"bytes\":%zu}\n",seconds(CLOCK_MONOTONIC),extra_mib*1024*1024);
        }
        if(extra_memory && now-epoch>=release_after) {
            extra_ok=checksum(extra_memory,extra_mib*1024*1024)==extra_checksum;
            munmap(extra_memory,extra_mib*1024*1024);extra_memory=NULL;
            printf("{\"event\":\"extra_released\",\"t\":%.9f,\"ok\":%s}\n",seconds(CLOCK_MONOTONIC),extra_ok?"true":"false");
        }
        if (!phase && now-epoch>=reuse_after) {
            phase=1; hot_mib=reuse_mib;
            printf("{\"event\":\"phase\",\"t\":%.9f,\"hot_mib\":%zu}\n",now,hot_mib);
        }
        size_t pages=hot_mib*1024*1024/page;
        for (size_t k=0; k<work_pages; ++k) {
            /* Keep the initially hot region at the high end of the mapping.
               The low-address cold prefix avoids a first-scan address-order
               artifact found during actuator calibration. Both donors use it. */
            size_t index=((mib-hot_mib)*1024*1024+(size_t)(mix64(seed+units)%pages)*page)/8;
            uint64_t value=((volatile uint64_t*)memory)[index];
            for (unsigned j=0;j<32;++j) value=mix64(value+j);
            result ^= value; ++units;
        }
        now=seconds(CLOCK_MONOTONIC);
        if (now-last>=0.25) {
            printf("{\"event\":\"progress\",\"t\":%.9f,\"units\":%" PRIu64 ",\"result\":\"%016" PRIx64 "\"}\n",now,units,result);
            last=now;
        }
        next+=tick;
        /* Do not catch up arbitrarily after a stall. Lateness reduces progress. */
        if (next<now) next=now+tick;
        pause_until(next);
    }
    printf("{\"event\":\"work_end\",\"t\":%.9f,\"units\":%" PRIu64 "}\n",seconds(CLOCK_MONOTONIC),units);
    uint64_t final=checksum(memory,size);
    if(extra_memory){extra_ok=checksum(extra_memory,extra_mib*1024*1024)==extra_checksum;munmap(extra_memory,extra_mib*1024*1024);}
    printf("{\"event\":\"verified\",\"t\":%.9f,\"ok\":%s,\"checksum\":\"%016" PRIx64 "\"}\n",
           seconds(CLOCK_MONOTONIC),initial==final&&extra_ok?"true":"false",final);
    munmap(memory,size);
    return initial==final&&extra_ok?0:3;
}
