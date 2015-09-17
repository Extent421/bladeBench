#include <stdio.h>
#include <string.h>

#include "HX711.h"
#include <SPI.h>
#include <SdFat.h>
#include <Servo.h>

// chip select for SD card
const uint8_t chipSelect = SS;
// File system object.
SdFat sd;

// Log file.
SdBaseFile file;


// HX711.DOUT	- pin #A1
// HX711.PD_SCK	- pin #A0
HX711 scale(A1, A0);

Servo ESC;

IntervalTimer logSampler;

float rawTemp;
float rawVolt;
float cValue;
float correctionFactor = .755/236; // ADC to volt.  Not accurate, but close enough for testing
double scaleValue;
//double loopCount = 0;
///double longestLoop = 0;
elapsedMillis loopTime;
elapsedMicros testTime;


const unsigned int BUFFERSIZE = 512; //buffer size for 1 SD block
const unsigned int MAXBUFFERS = 20; //number of blocks in the ring buffer
uint32_t const ERASE_SIZE = 262144L;
const uint32_t FILE_BLOCK_COUNT = 256000;

// ring buffer indexes
uint8_t writeIndex = 0;
uint8_t readIndex = 0;
unsigned int overrun = 0;

struct buffer {
  char data[BUFFERSIZE+1];
  volatile bool full = false;
};

buffer writeBuffer[MAXBUFFERS];

void setup() {
	Serial.begin(115200);
	if (!sd.begin(chipSelect, SPI_FULL_SPEED)) {
		sd.initErrorHalt();
	}
	delay(1000); // pause for slow serial adaptors
	ESC.attach(9);  // attaches the servo on pin 9 to the servo object
	ESC.writeMicroseconds(1001);
	setupLoadCell();

	//zero out all of the write buffers
	for (unsigned int i=0; i<MAXBUFFERS; i++ ) {
		memset(writeBuffer[i].data, 0, BUFFERSIZE+1);
	}
}

void log(){
	double a1;
	double a2;
	double a3;
	double a4;
	int commandValue;
	char str[80];
	unsigned long time;

	//check if we're sitting in an overflow state and dump the sample if needed
	if (writeBuffer[writeIndex].full==true) {
		overrun++;
		return;
	}

	//record the current time for the start of the sample
	time = testTime;
	// do some ADC reads
	// TODO make use of dual synchronous ADC
	// TODO interleave ADC start and ADC end with rest of sample calcs
	rawTemp = analogRead(A8);
	a1 = getTemp(rawTemp);
	rawTemp = analogRead(A8);
	a2 = getTemp(rawTemp);
	rawTemp = analogRead(A8);
	a3 = getTemp(rawTemp);
	rawTemp = analogRead(A8);
	a4 = getTemp(rawTemp);

	// check the loadcell for updates
	updateScaleValue();

	//make note of the current command micros for the ESC
	commandValue = ESC.readMicroseconds();

	//format the CSV line
	sprintf(str, "%lu, %i, %.3f, %.3f, %.3f, %.3f, %.2f\n", time, commandValue, a1, a2, a3, a4, scaleValue);

	//write the CSV line to the block buffer
	size_t thisLength;
	size_t bufferLength;
	size_t bufferFree;
	thisLength = strlen(str);
	bufferLength = strlen(writeBuffer[writeIndex].data);
	bufferFree = BUFFERSIZE - bufferLength;
	// if the current sample is longer than the space in the current buffer
	if (thisLength > bufferFree) {
		// check for buffer overflow, discard the whole sample if there's not room
		uint8_t nextIndex = nextBuffer(writeIndex);
		if (writeBuffer[writeIndex].full==true) {
			overrun++;
			return;
		}

		// if not advance to the next buffer index
		strncat(writeBuffer[writeIndex].data, str, bufferFree);
		writeBuffer[writeIndex].full = true;
		writeIndex = nextIndex;

		//and finish writing the CSV line
		strcat(writeBuffer[writeIndex].data, &str[bufferFree]);

	} else {
		// no overflow, just write the whole CSV line to the current buffer
		strcat(writeBuffer[writeIndex].data, str);
	}
}

unsigned int nextBuffer(unsigned int index){
	// return the next index for the ring buffer
	index++;
	if (index >= MAXBUFFERS) {
		index = 0;
	}
	return (index);
}

void loop() {
	//dump anything sitting in the serial buffer
	while (Serial.read() >= 0) {}
	Serial.println();
	Serial.println(F("type:"));
	Serial.println(F("r - run"));

	//spin while waiting for user input
	while(!Serial.available()) {}
	char c = tolower(Serial.read());

	// Discard extra Serial data.
	do {
	delay(10);
	} while (Serial.read() >= 0);

	if (c == 'r') {
	  doTestLog();
	} else {
	Serial.println(F("Invalid entry"));
	}

}

void doTestLog() {
	Serial.println("type s to end");
	char c;
	uint32_t blocksWritten = 0;

	//get logfile name
	char logName[] = "log00.txt";
	uint8_t nameLength = 3;
	while (sd.exists(logName)) {
	if (logName[nameLength + 1] != '9') {
		logName[nameLength + 1]++;
	} else {
		logName[nameLength + 1] = '0';
	  if (logName[nameLength] == '9') {
		  Serial.println("Can't create file name");
		return;
	  }
	  logName[nameLength]++;
	}
	}
	createLogFile(logName);

	// start the log sampling ISR
	logSampler.priority(200); // set lowish priority.  We want to let regular fast ISRs (like servo timing) to be able to interrupt
	logSampler.begin(log, 1000); // start logger, 1000 micros = 1khz
	boolean running = true;

	// start spinning on the ring buffer, writing to disk as soon as each block fills
	while(running){
		if ( writeBuffer[readIndex].full == true){
			// wait for the sd card to finish it's current write
			if (!sd.card()->isBusy()) {
				char* pBlock = &writeBuffer[readIndex].data[0]; // pointer to the next block buffer to write to disk
				if (!sd.card()->writeData((uint8_t*)pBlock)) {
					Serial.println("write data failed");
				}
				blocksWritten++;
				//TODO handle max blocks overrun
				//Serial.print(writeBuffer[readIndex].data);
				//zero out the written block buffer
				memset(writeBuffer[readIndex].data, 0, sizeof(writeBuffer[readIndex].data));
				// mark it as available in the ringbuffer
				writeBuffer[readIndex].full = false;
				readIndex = nextBuffer(readIndex);
				if (overrun > 0) {
					Serial.print("over ");
					Serial.print(overrun);
				}
			}
		}

		//check for serial abort
		if (Serial.available()){
			c = tolower(Serial.read());

			if (c=='s'){
				running = false;
				// kill the log sampling ISR
				logSampler.end();
				Serial.println("log end");

				// TODO finish writting out the rest of the ring buffer
				//wait for the current SD write to finish
				while (sd.card()->isBusy()) {}
				if (!sd.card()->writeStop()) {
					Serial.println("writeStop failed");
				}
				// Truncate file if recording stopped early.
				if (blocksWritten != FILE_BLOCK_COUNT) {
					Serial.println(F("Truncating file"));
					if (!file.truncate(512L * blocksWritten)) {
						Serial.println("Can't truncate file");
					}
				}
			}
		}
	}
}

void createLogFile(char logfile[]){
	// TODO actually do something with SD error conditions instead of just ignoring them
	uint32_t bgnBlock, endBlock;

	Serial.print("opening file");
	Serial.println(logfile);

	//create the logfile
	if (!file.createContiguous(sd.vwd(),
			logfile, 512 * FILE_BLOCK_COUNT)) {
		Serial.println("createContiguous failed");
	  }
	  // Get the address of the file on the SD.
	  if (!file.contiguousRange(&bgnBlock, &endBlock)) {
		  Serial.println("contiguousRange failed");
	  }

	  // Flash erase all data in the file.
	    Serial.println(F("Erasing all data"));
	    uint32_t bgnErase = bgnBlock;
	    uint32_t endErase;
	    while (bgnErase < endBlock) {
	      endErase = bgnErase + ERASE_SIZE;
	      if (endErase > endBlock) {
	        endErase = endBlock;
	      }
	      if (!sd.card()->erase(bgnErase, endErase)) {
	    	  Serial.println("erase failed");
	      }
	      bgnErase = endErase + 1;
	    }
	    // Start a multiple block write.
	    if (!sd.card()->writeStart(bgnBlock, FILE_BLOCK_COUNT)) {
	    	Serial.println("writeBegin failed");
	    }
}

double getTemp(float rawValue){
	// convert raw ADC reading into temperature in degrees C

	//for TMP36
	//get absolute voltage
	double rawVolt = rawValue*correctionFactor;
	//get temperature from voltage
	double cValue = ((rawVolt - .750)*100) + 24;
	return cValue;
}

void setupLoadCell() {
	// TODO: calibration
	scale.set_scale(2280.f);          // this value is obtained by calibrating the scale with known weights;
	scale.tare(8);				        // reset the scale to 0, 8 samples average
}

void powerScale() {
	// nothing going on here yet
	scale.power_down();			        // put the ADC in sleep mode
	scale.power_up();
}

void updateScaleValue() {
	// update the global measurement value, but only if the scale is ready to be read
	if (scale.is_ready()){
		scaleValue = scale.get_value();
	}
}
