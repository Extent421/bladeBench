#include <stdint.h>


// command modes
#define MODE_END		0	//stop test
#define MODE_RAMP		1	//ramp speed over time
#define MODE_HOLD		2	//hold steady speed
#define MODE_TARE		3	//reset the scale
#define MODE_TACH		4	//calibrate the tach
#define MODE_LOG_TACH	5	//calibrate the tach

#define ABORT_NONE		0	//do not abort
#define ABORT_TESTEND	1	//normal test end
#define ABORT_USER		2	//user requested abort
#define ABORT_DANGER	3	//emergency stop condition triggered

// bitflags for sample stream
#define SAMPLE_TIME			1<<0
#define SAMPLE_MOTORCOMMAND	1<<1
#define SAMPLE_TACH			1<<2
#define SAMPLE_VOLT			1<<3
#define SAMPLE_AMP			1<<4
#define SAMPLE_THRUST		1<<5
#define SAMPLE_T1			1<<6
#define SAMPLE_T2			1<<7
#define SAMPLE_T3			1<<8
#define SAMPLE_T4			1<<9
#define SAMPLE_TACH_INDEX	1<<10
#define SAMPLE_CALIBRATE	1<<11
#define SAMPLE_AUXCOMMAND	1<<12


const unsigned int COMMANDBUFFER_SIZE = 100; //buffer for benchmark commands

struct command {
	uint8_t mode = 0;
	unsigned long time = 0;
	uint16_t value = 0;
	int16_t value2 = -1;
	bool useMicros = false;
};

struct vCalibration {
	float active = 0;
	float activeOffset = 0;
	float cell3 = 3665;
	float cell4 = 0;
	float cell5 = 0;
	float cell6 = 13.0153255458302;
	float cell3Offset = 115;
	float cell4Offset = 0;
	float cell5Offset = 0;
	float cell6Offset = 0;
	float amp = 730;
	float ampOffset = 295;
};

union byteMap {
	uint8_t uint8[4];
	uint16_t uint16[2];
	uint32_t uint32;
	float flt;
	int i[2];
	unsigned long ulong;
	long slong;
};


struct rawSampleStruct {
	unsigned long time = 0;
	bool T1Present = false;
	uint16_t T1 = 0;
	bool T2Present = false;
	uint16_t T2 = 0;
	bool T3Present = false;
	uint16_t T3 = 0;
	bool T4Present = false;
	uint16_t T4 = 0;
	bool thrustPresent = false;
	long thrust = 0;
	bool commandValuePresent = false;
	uint16_t commandValue = 0;
	bool auxValuePresent = false;
	uint16_t auxValue = 0;
	bool tachPulsePresent = false;
	unsigned long tachPulse=0;
	uint8_t tachIndex=0;
	bool calibrate = false;
	bool voltsPresent = false;
	uint16_t volts = 0;
	bool ampsPresent = false;
	uint16_t amps = 0;
	volatile bool ready = false;
};


