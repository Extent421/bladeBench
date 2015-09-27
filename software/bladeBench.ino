#include "bladeBench.h"
#include "pins.h"

#include <string.h>
#include <stdio.h>

#include "HX711.h"
#include <SPI.h>
#include <SdFat.h>
#include <Servo.h>
#include <ADC.h>

// File system object.
SdFat sd;

// Log file.
SdBaseFile file;

// adc object
ADC *adc = new ADC();
ADC::Sync_result ADCresult;

HX711 scale(HX_DAT_PIN, HX_CLK_PIN);
float scaleCalibrationValue = 392.9;

Servo ESC;

IntervalTimer logSampler;
IntervalTimer commandTrigger;

float rawTemp;
float rawVolt;
float cValue;
float correctionFactor = 2.5/(2^16); // ADC to volt. 2.5v external reference
double scaleValue;
//double loopCount = 0;
double longestLoop = 0;
elapsedMillis loopTime;
elapsedMicros testTime;
elapsedMicros commandTime;

elapsedMicros tachTime;
volatile unsigned long lastTachPulse = 0;
uint8_t pulsesPerRev = 2;

elapsedMillis buttonTime;
bool buttonRunning = false;
bool buttonLatch = false;
bool buttonDown = false;

bool abortTest = false;
uint8_t abortReason = ABORT_NONE;


float motorValue=0;

const unsigned int MAXBUFFERS = 20; //number of blocks in the ring buffer
uint32_t const ERASE_SIZE = 262144L;
const uint32_t FILE_BLOCK_COUNT = 256000;

// ring buffer indexes
uint8_t writeIndex = 0;
uint8_t readIndex = 0;
unsigned int overrun = 0;

uint16_t commandUpdateRate = 333; // ESC update in hz
uint32_t commandUpdateRateMicros = (1.0/commandUpdateRate)*1000000;

uint16_t sampleRate = 1000; // log sampler rate in hz
uint32_t sampleRateMicros = (1.0/sampleRate)*1000000;

command commandBuffer[100];
volatile uint8_t commandIndex = 0;
float commandIncrement = 0; //number of microseconds to increment the servo object each command loop
unsigned long commandMicros = 0; //number of microseconds to run the current command for

buffer writeBuffer[MAXBUFFERS];

void runCurrentCommand() {
	int commandValue = 0;
	unsigned long updateCount = 0;
	commandTrigger.priority(180);

	switch (commandBuffer[commandIndex].mode){
	case MODE_END:
		ESC.writeMicroseconds(1000);
		commandTrigger.end();
		logSampler.end();
		commandIndex=0;
		abortTest=true;
		abortReason = ABORT_TESTEND;


		break;
	case MODE_RAMP:
		// reset the command timer
		commandTime = 0;
		motorValue = ESC.readMicroseconds();
		// grab the total length of the command
		if (commandBuffer[commandIndex].useMicros){
			commandMicros = commandBuffer[commandIndex].time;
		} else {
			commandMicros = commandBuffer[commandIndex].time * 1000;
		}
		// pre-calculate the ESC increment for each command loop
		commandValue = ESC.readMicroseconds();
		updateCount = commandMicros/commandUpdateRateMicros;
		commandIncrement = (float)(commandBuffer[commandIndex].value - commandValue)/updateCount;
		// kick off the command loop
		commandTrigger.begin(commandISR, commandUpdateRateMicros);

		break;
	case MODE_HOLD:
		ESC.writeMicroseconds(commandBuffer[commandIndex].value);
		commandTime = 0;

		if (commandBuffer[commandIndex].useMicros){
			commandMicros = commandBuffer[commandIndex].time;
		} else {
			commandMicros = commandBuffer[commandIndex].time * 1000;
		}
		commandTrigger.begin(commandISR, commandMicros);

		break;

	}
}

void commandISR(){
	if( commandTime > commandMicros ){
		// this command is over time, make sure the final value is set and then advance
		ESC.writeMicroseconds(commandBuffer[commandIndex].value);
		commandIndex++;
		runCurrentCommand();
		return;
	}
	motorValue += commandIncrement;
	ESC.writeMicroseconds(motorValue);

}

void setup() {
	pinMode(BUTTON_PIN, INPUT_PULLUP);
	pinMode(TACH_PIN, INPUT);
	pinMode(T1_PIN, INPUT);
	pinMode(T2_PIN, INPUT);
	pinMode(T3_PIN, INPUT);
	pinMode(VSENSE_PIN, INPUT);
	pinMode(ISENSE_PIN, INPUT);

	adc->setReference(ADC_REF_EXT, ADC_0);
    adc->setAveraging(16, ADC_0); // set number of averages
    adc->setResolution(16, ADC_0); // set bits of resolution
    adc->setConversionSpeed(ADC_MED_SPEED, ADC_0); // change the conversion speed
    adc->setSamplingSpeed(ADC_MED_SPEED  , ADC_0); // change the sampling speed

	adc->setReference(ADC_REF_EXT, ADC_1);
    adc->setAveraging(16, ADC_1); // set number of averages
    adc->setResolution(16, ADC_1); // set bits of resolution
    adc->setConversionSpeed(ADC_MED_SPEED, ADC_1); // change the conversion speed
    adc->setSamplingSpeed(ADC_MED_SPEED  , ADC_1); // change the sampling speed

    //adc->enableCompare(1.0/2.5*adc->getMaxValue(ADC_0), 0, ADC_0);
    //adc->enableCompare(1.0/2.5*adc->getMaxValue(ADC_1), 0, ADC_1);
    //while (!adc->isComplete(ADC_0)){};
    //while (!adc->isComplete(ADC_1)){};

    correctionFactor = 2.5/adc->getMaxValue(ADC_0);

	Serial.begin(115200);
	if (!sd.begin(SC_CS_PIN, SPI_FULL_SPEED)) {
		sd.initErrorHalt();
	}
	delay(1000); // pause for slow serial adaptors
	ESC.attach(ESC_PIN);  // attaches the servo on pin 9 to the servo object
	ESC.writeMicroseconds(1001);
	setupLoadCell();


	//zero out all of the write buffers
	for (unsigned int i=0; i<MAXBUFFERS; i++ ) {
		memset(writeBuffer[i].data, 0, BUFFERSIZE+1);
	}
}

void tachISR() {
	unsigned long time;
	time = tachTime;
	lastTachPulse = time ;
	tachTime = tachTime - time;
}

void buildTest(){
	//reset the entire command buffer
	for (unsigned int i=0; i<100; i++ ) {
		commandBuffer[i].mode = MODE_END;
		commandBuffer[i].time = 0;
		commandBuffer[i].value = 0;
		commandBuffer[i].useMicros = false;
	}

	commandBuffer[0].mode = MODE_HOLD;
	commandBuffer[0].time = 1000;
	commandBuffer[0].value = 1000;
	commandBuffer[1].mode = MODE_HOLD;
	commandBuffer[1].time = 1000;
	commandBuffer[1].value = 1100;
	commandBuffer[2].mode = MODE_RAMP;
	commandBuffer[2].time = 4000;
	commandBuffer[2].value = 2000;
	commandBuffer[3].mode = MODE_HOLD;
	commandBuffer[3].time = 2000;
	commandBuffer[3].value = 2000;
	commandBuffer[4].mode = MODE_HOLD;
	commandBuffer[4].time = 1000;
	commandBuffer[4].value = 1100;
	commandBuffer[5].mode = MODE_HOLD;
	commandBuffer[5].time = 2000;
	commandBuffer[5].value = 1250;
	commandBuffer[6].mode = MODE_HOLD;
	commandBuffer[6].time = 1000;
	commandBuffer[6].value = 1100;
	commandBuffer[7].mode = MODE_HOLD;
	commandBuffer[7].time = 2000;
	commandBuffer[7].value = 1500;
	commandBuffer[8].mode = MODE_HOLD;
	commandBuffer[8].time = 1000;
	commandBuffer[8].value = 1100;
	commandBuffer[9].mode = MODE_HOLD;
	commandBuffer[9].time = 2000;
	commandBuffer[9].value = 1750;
	commandBuffer[10].mode = MODE_HOLD;
	commandBuffer[10].time = 1000;
	commandBuffer[10].value = 1100;
	commandBuffer[11].mode = MODE_HOLD;
	commandBuffer[11].time = 2000;
	commandBuffer[11].value = 2000;
	commandBuffer[12].mode = MODE_HOLD;
	commandBuffer[12].time = 1000;
	commandBuffer[12].value = 1100;
	commandBuffer[13].mode = MODE_HOLD;
	commandBuffer[13].time = 1000;
	commandBuffer[13].value = 1000;


}

void log(){
	double a1;
	double a2;
	double a3;
	double a4;
	int commandValue;
	char str[80];
	unsigned long time;
	unsigned long endTime;
	unsigned long totalTime;
	double RPM=0;

	//check if we're sitting in an overflow state and dump the sample if needed
	if (writeBuffer[writeIndex].full==true) {
		overrun++;
		return;
	}

	//record the current time for the start of the sample
	time = testTime;
	// do some ADC reads
	// TODO interleave ADC start and ADC end with rest of sample calcs


    //ADCresult = adc->analogSynchronizedRead(T2_PIN, T3_PIN);
    while (!adc->isComplete()){};
    ADCresult = adc->readSynchronizedContinuous();

    adc->startSynchronizedSingleRead(ISENSE_PIN, VSENSE_PIN);
    // if using 16 bits and single-ended is necessary to typecast to unsigned,
    // otherwise values larger than 3.3/2 will be interpreted as negative
    a1 = getTemp( (uint16_t)ADCresult.result_adc0 );
    a2 = getTemp( (uint16_t)ADCresult.result_adc1 );

    //ADCresult = adc->analogSynchronizedRead(ISENSE_PIN, VSENSE_PIN);

    /*
	rawTemp = (uint16_t)adc->analogRead(T1_PIN, ADC_0);
	a1 = getTemp(rawTemp);
	rawTemp = (uint16_t)adc->analogRead(T2_PIN, ADC_0);
	a2 = getTemp(rawTemp);
	rawTemp = (uint16_t)adc->analogRead(VSENSE_PIN, ADC_0);
	a3 = getVolts(rawTemp);
	rawTemp = (uint16_t)adc->analogRead(ISENSE_PIN, ADC_0);
	a4 = getAmps(rawTemp);
	*/
	// check the loadcell for updates
	updateScaleValue();

	//make note of the current command micros for the ESC
	commandValue = ESC.readMicroseconds();

	//RPM
	RPM = ((1000000.0/lastTachPulse)/pulsesPerRev )*60;

    while (!adc->isComplete()){};
    ADCresult = adc->readSynchronizedSingle();
    adc->startSynchronizedContinuous(T2_PIN, T3_PIN);

    a3 = getVolts( (uint16_t)ADCresult.result_adc1 );
    a4 = getAmps( (uint16_t)ADCresult.result_adc0 );

	//format the CSV line
	sprintf(str, "%lu, %i, %.3f, %.1f, %.1f, %.3f, %.3f, %.2f\n", time, commandValue, RPM, a1, a2, a3, a4, scaleValue);
	writeToBuffer(str);

	endTime = testTime;
	totalTime = endTime - time;
	if (totalTime > longestLoop){
		longestLoop = totalTime;
	}


}

void writeToBuffer(const char* str){
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
		if (writeBuffer[nextIndex].full==true) {
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

void buttonHandler() {

	if (buttonRunning){ //button is running
		if ( buttonTime > 2 ) { //if we're over the debounce timer and not latched do the 2nd check
			if (!digitalRead(BUTTON_PIN)) {  // if it's still triggered trigger the button event and latch
				buttonDown=true;
				buttonLatch=true;
				buttonRunning = false;
			} else {	// if it's not running then stop running the button
				buttonRunning = false;
			}
		}

	} else { //button is not running
		if (!digitalRead(BUTTON_PIN)) {//button not running and on
			if (!buttonLatch){ //if not latched and not running start the button counter
				buttonRunning = true;
				buttonTime = 0;
			}
		} else { //button not running and off, reset latch
			buttonLatch = false;
		}
	}

}

void loop() {
	//dump anything sitting in the serial buffer
	while (Serial.read() >= 0) {}
	Serial.println();
	Serial.println(F("type:"));
	Serial.println(F("r - run"));

	//spin while waiting for user input
	while(!Serial.available()) {

		buttonHandler();
		if (buttonDown){
			buttonDown = false;
			doTestLog();
			return;
		}

	}
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
	Serial.println("logging...");

	buildTest();
	abortReason = ABORT_NONE;

	logHead();

	// start the log sampling ISR
	attachInterrupt(TACH_PIN, tachISR, FALLING);
	tachTime = 0;
	lastTachPulse = 30000000*pulsesPerRev; //start tach at 1 rpm

	//startup the ADC so it's ready to read on the first sample
    adc->startSynchronizedContinuous(T2_PIN, T3_PIN);
	logSampler.priority(200); // set lowish priority.  We want to let regular fast ISRs (like servo timing) to be able to interrupt
	logSampler.begin(log, sampleRateMicros); // start logger
	runCurrentCommand();

	bool running = true;
	bool flushing=false; //status flag for when the test is finished and we're flushing to disk

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
				memset(writeBuffer[readIndex].data, 0, BUFFERSIZE+1);
				// mark it as available in the ringbuffer
				writeBuffer[readIndex].full = false;
				readIndex = nextBuffer(readIndex);
				if (overrun > 0) {
					Serial.print("over ");
					Serial.print(overrun);
				}
			}
		}

		buttonHandler();
		if (buttonDown){
			buttonDown = false;
			abortTest = true;
			abortReason = ABORT_USER;
		}
		//check for serial abort
		if (Serial.available()){
			c = tolower(Serial.read());

			if (c=='s'){
				abortTest=true;
				abortReason = ABORT_USER;

			}
		}

		if (abortTest){ //trigger the end of the test
			abortTest=false;
			flushing = true;
			// reset the ESC and kill the command ISR
			ESC.writeMicroseconds(1000);
			commandTrigger.end();
			//reset the command program to the beginning
			commandIndex=0;
			// kill the log sampling ISR
			logSampler.end();
			// kill the tach ISR
			detachInterrupt(TACH_PIN);
			//add any tail info to the log file
			logTail();
			//flag the current write index as full
			writeBuffer[writeIndex].full = true;

			Serial.print("longest loop ");
			Serial.print(longestLoop);
			Serial.print("/");
			Serial.print(sampleRateMicros);
			Serial.print(" ");
			Serial.println((float)longestLoop/sampleRateMicros);

		}

		if ( flushing && (writeBuffer[readIndex].full == false) ){

			//buffer is flushed, end the test loop
			running = false;
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

	Serial.println("log completed");
}

void logHead(){
	double ambientTemp;
	char str[80];

    adc->setAveraging(32, ADC_0); // set number of averages
	rawTemp = (uint16_t)adc->analogRead(T3_PIN, ADC_0);
    adc->setAveraging(16, ADC_0); // set number of averages

    ambientTemp = getTemp(rawTemp);

	sprintf(str, "ambient temp: %.1f\n", ambientTemp );
	writeToBuffer(str);
	sprintf(str, "pulse per rev: %i\n", pulsesPerRev );
	writeToBuffer(str);
	sprintf(str, "loadcell calibration value: %.2f\n", scaleCalibrationValue );
	writeToBuffer(str);
	sprintf(str, "command update rate: %i\n", commandUpdateRate );
	writeToBuffer(str);
	writeToBuffer("motor: \n");
	writeToBuffer("ESC: \n");
	writeToBuffer("settings: \n");
	writeToBuffer("firmware: \n");
	writeToBuffer("prop: \n");
	writeToBuffer("power: \n");
	writeToBuffer("\n");

	writeToBuffer("Time, Motor Command, RPM, ESC Temp, Motor Temp, Volt, Amp, Thrust\n");

}

void logTail(){
	char str[80];
	writeToBuffer("\n");

	switch (abortReason){
	case ABORT_NONE:
		break;
	case ABORT_TESTEND:
		break;
	case ABORT_USER:
		writeToBuffer("Test aborted: user request");
		break;
	case ABORT_DANGER:
		writeToBuffer("Test aborted: emergency stop condition");
		break;
	}

	if (overrun > 0 ) {
		sprintf(str, "dropped samples: %i\n", overrun );
		writeToBuffer(str);
	}
}


void createLogFile(const char logfile[]){
	// TODO actually do something with SD error conditions instead of just ignoring them
	uint32_t bgnBlock, endBlock;

	Serial.print("opening file ");
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

double getTemp(const float rawValue){
	// convert raw ADC reading into temperature in degrees C

	//get absolute voltage
	double rawVolt = rawValue*correctionFactor;
	//get temperature from voltage

	//TMP36
	//double cValue = ((rawVolt - .750)*100) + 24;
	//TMP35
	double cValue = ((rawVolt - .250)*100) + 24;
	return cValue;
}

double getVolts(const float rawValue){
	// convert raw ADC reading into battery voltage

	//get absolute voltage
	double rawVolt = rawValue*correctionFactor;

	//AttoPilot 90A sensor
	double vValue = rawVolt*(1.0/0.06369) ;
	return vValue;
}

double getAmps(const float rawValue){
	// convert raw ADC reading into battery voltage

	//get absolute voltage
	double rawVolt = rawValue*correctionFactor;

	//AttoPilot 90A sensor
	double aValue = rawVolt*(1.0/0.0366) ;
	return aValue;
}

void setupLoadCell() {
	// TODO: calibration
	scale.set_scale(scaleCalibrationValue);          // this value is obtained by calibrating the scale with known weights;
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
		scaleValue = scale.get_units();
	}
}
