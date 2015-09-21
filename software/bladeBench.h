#include <stdint.h>



// command modes
#define MODE_END	0	//stop test
#define MODE_RAMP	1	//ramp speed over time
#define MODE_HOLD	2	//hold steady speed

const unsigned int BUFFERSIZE = 512; //buffer size for 1 SD block

struct command {
	uint8_t mode = 0;
	unsigned long time = 0;
	unsigned long value = 0;
	bool useMicros = false;
};


struct buffer {
  char data[BUFFERSIZE+1];
  volatile bool full = false;
};
