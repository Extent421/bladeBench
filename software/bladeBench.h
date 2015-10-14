#include <stdint.h>



// command modes
#define MODE_END	0	//stop test
#define MODE_RAMP	1	//ramp speed over time
#define MODE_HOLD	2	//hold steady speed
#define MODE_TARE	3	//reset the scale

#define ABORT_NONE		0	//do not abort
#define ABORT_TESTEND	1	//normal test end
#define ABORT_USER		2	//user requested abort
#define ABORT_DANGER	3	//emergency stop condition triggered

const unsigned int BUFFERSIZE = 512; //buffer size for 1 SD block
const unsigned int COMMANDBUFFER_SIZE = 100; //buffer size for 1 SD block

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
