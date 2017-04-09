#include "bladeBench.h"
#include "pins.h"
#include "ringIndexManager.h"
#include "ad5272.h"
#include "dshot.h"

#include <string.h>
#include <stdio.h>

#include "HX711.h"
#include <SPI.h>
#include <SdFat.h>
#include <Servo.h>
#include <ADC.h>
#include <i2c_t3.h>

// File system object.
SdFatSdioEX sd;

// Log file.
File file;

// adc object
ADC *adc = new ADC();
ADC::Sync_result ADCresult;

HX711 scale(HX_DAT_PIN, HX_CLK_PIN);
float scaleCalibrationValue = 392.9;

Servo ESC;

IntervalTimer logSampler;
IntervalTimer scaleUpdate;
IntervalTimer commandTrigger;
IntervalTimer idler;

uint16_t adcMaxValue = 0;
float vRef = 3;

float rawTemp;
float rawVolt;
float cValue;
float correctionFactor = 2.5/(2^16); // ADC to volt. 2.5v external reference
float scaleValue;
volatile bool scaleUpdated = false;

//double loopCount = 0;
uint16_t longestLoop = 0;
uint16_t idleTimeMax = 0;
uint16_t idleTimeMin = 9999;
uint16_t maxSampleBuffer = 0;

elapsedMillis loopTime;
elapsedMicros testTime;
elapsedMicros commandTime;
elapsedMillis lastTempReadingTimer;


//uint8_t tachTriggerType = RISING;
uint8_t tachTriggerType = RISING;

elapsedMicros tachTime;
volatile unsigned long lastTachPulse = 0;
volatile uint8_t tachPulseCount = 0;
uint8_t pulsesPerRev = 2;
volatile bool tachUpdate = false;
uint16_t tachDebounce = 0;
float tachCalibrationData[10];
unsigned long tachCalibrationTemp[10];
ringIndexManager tachCalibrationIndex(2);
volatile bool tachCalibrated = 0;
volatile bool tachCalibrateRunning = 0;
uint16_t tachCalibrationCount = 0;


elapsedMillis buttonTime;
bool buttonRunning = false;
bool buttonLatch = false;
bool buttonDown = false;

bool abortTest = false;
uint8_t abortReason = ABORT_NONE;


float motorValue=0;

const uint16_t MAXSAMPLES = 4000; //number of blocks in the ring buffer

// ring buffer indexes
unsigned int overrunS = 0;

ringIndexManager sampleBufferIndex(MAXSAMPLES);
rawSampleStruct sampleBuffer[MAXSAMPLES];

ringIndexManager tempIndex(4);
const byte tempPins[4] = {T1_PIN,T2_PIN,T3_PIN,T4_PIN};
volatile uint16_t tempValues[4] = {0,0,0,0};
volatile bool tempUpdate[4] = {false,false,false,false};
volatile bool tempEnable[4] = {false,false,false,false};
uint16_t thermBValue = 3435;

uint16_t commandUpdateRate = 333; // ESC update in hz
uint32_t commandUpdateRateMicros = (1.0/commandUpdateRate)*1000000;

uint16_t idleUpdateRate = 250; // ESC update in hz  Dshot timeout is 200hz
uint32_t idleUpdateRateMicros = (1.0/idleUpdateRate)*1000000;
elapsedMicros commandIdleTime;

uint16_t sampleRate = 1000; // log sampler rate in hz
uint32_t sampleRateMicros = (1.0/sampleRate)*1000000;

volatile bool samplerActive = false;

command commandBuffer[COMMANDBUFFER_SIZE];
volatile uint8_t commandIndex = 0;
float commandIncrement = 0; //number of microseconds to increment the servo object each command loop
unsigned long commandMicros = 0; //number of microseconds to run the current command for

char sChar;
char serialCommand[256];
int serialCommandIndex = 0;
bool scReading = false;


void setup() {


	pinMode(BUTTON_PIN, INPUT_PULLUP);
	pinMode(TACH_PIN, INPUT);
	pinMode(T1_PIN, INPUT);
	pinMode(T2_PIN, INPUT);
	pinMode(T3_PIN, INPUT);
	pinMode(T4_PIN, INPUT);
	pinMode(VSENSE_PIN, INPUT);
	pinMode(ISENSE_PIN, INPUT);
	pinMode(ISENSE2_PIN, INPUT);


	pinMode(ESC_PIN, OUTPUT);
	digitalWrite(ESC_PIN, 0);

	pinMode(RANGE_3S, OUTPUT);
	digitalWrite(RANGE_3S, 0);
	pinMode(RANGE_4S, OUTPUT);
	digitalWrite(RANGE_4S, 0);
	pinMode(RANGE_5S, OUTPUT);
	digitalWrite(RANGE_5S, 0);
	pinMode(CALIBRATION_SENSE, OUTPUT);
	digitalWrite(CALIBRATION_SENSE, 0);
	pinMode(BATTERY_SENSE, OUTPUT);
	digitalWrite(BATTERY_SENSE, 0);

	Serial.begin(115200);
	Serial5.begin(115200);
	//while (!Serial) {	}

	Serial.println("starting up");

	if (!sd.begin()) {
		Serial.println("SdFatSdioEX begin failed");
	}
	sd.chvol();

	setSamplerADCSettings();

    scaleUpdate.priority(240); // set very low priority
	logSampler.priority(200); // set lowish priority.  We want to let regular fast ISRs (like servo timing) to be able to interrupt


	//ESC.attach(ESC_PIN);  // attaches the servo on pin 9 to the servo object
	//ESC.writeMicroseconds(1001);
	setupLoadCell();

	Wire2.begin(I2C_MASTER, 0x00, I2C_PINS_3_4, I2C_PULLUP_EXT, 400000);
	Wire2.setDefaultTimeout(10000); // 10ms
	enableWiper();
	setWiper(270);

	memset(serialCommand, 0, 256);

	setupDshotDMA();

	idler.begin(idleISR, idleUpdateRateMicros);

	pinMode(LED_PIN, OUTPUT);
	digitalWrite(LED_PIN, 1);

}


void runCurrentCommand() {
	uint16_t commandValue = 0;
	unsigned long updateCount = 0;
	commandTrigger.priority(180);

	if(tachCalibrateRunning){ // if the tach calibration was running reset the ISR
		detachInterrupt(TACH_PIN);
		attachInterrupt(TACH_PIN, tachISR, tachTriggerType);
		tachCalibrateRunning = false;
	}

	switch (commandBuffer[commandIndex].mode){
	case MODE_END:
		//ESC.writeMicroseconds(1000);
		commandTrigger.end();
		logSampler.end();
		//dshotOut(48);

		idler.begin(idleISR, idleUpdateRateMicros);

		commandIndex=0;
		abortTest=true;
		abortReason = ABORT_TESTEND;
		break;
	case MODE_RAMP:
		// reset the command timer
		commandTime = 0;
		//motorValue = ESC.readMicroseconds();
		motorValue = readDshot();

		// grab the total length of the command
		if (commandBuffer[commandIndex].useMicros){
			commandMicros = commandBuffer[commandIndex].time;
		} else {
			commandMicros = commandBuffer[commandIndex].time * 1000;
		}
		// pre-calculate the ESC increment for each command loop
		//commandValue = ESC.readMicroseconds();
		commandValue = readDshot();
		updateCount = commandMicros/commandUpdateRateMicros;
		commandIncrement = (float)(commandBuffer[commandIndex].value - commandValue)/updateCount;
		// kick off the command loop
		commandTrigger.begin(commandISR, commandUpdateRateMicros);
		break;
	case MODE_HOLD:
		//ESC.writeMicroseconds(commandBuffer[commandIndex].value);
		//dshotOut(commandBuffer[commandIndex].value);
		commandTime = 0;

		if (commandBuffer[commandIndex].useMicros){
			commandMicros = commandBuffer[commandIndex].time;
		} else {
			commandMicros = commandBuffer[commandIndex].time * 1000;
		}
		commandTrigger.begin(commandISR, commandUpdateRateMicros);
		commandIncrement = 0;
		motorValue = commandBuffer[commandIndex].value;

		break;
	case MODE_TACH:
		commandTime = 0;

		if (commandBuffer[commandIndex].useMicros){
			commandMicros = commandBuffer[commandIndex].time;
		} else {
			commandMicros = commandBuffer[commandIndex].time * 1000;
		}
		commandTrigger.begin(commandISR, commandUpdateRateMicros);
		commandIncrement = 0;
		motorValue = commandBuffer[commandIndex].value;
		detachInterrupt(TACH_PIN);
		attachInterrupt(TACH_PIN, tachCalibrationISR, tachTriggerType);
		tachCalibrateRunning = true;


		break;
	case MODE_TARE:
		tare();
		commandIndex++;
		runCurrentCommand();
		break;
	}
}

void testISR(){
	//commandTrigger.end();

	dshotOut(48);

	//commandTrigger.begin(testISR, 1000); // start logger


}

void idleISR(){
	dshotThrottle(1);
}

void commandISR(){
	if( commandTime > commandMicros ){
		// this command has run over its end time, make sure the final value is set and then advance
		//ESC.writeMicroseconds(commandBuffer[commandIndex].value);
		//motorValue = commandBuffer[commandIndex].value;
		commandIndex++;
		runCurrentCommand();
		//return;
	}
	motorValue += commandIncrement;
	//ESC.writeMicroseconds(motorValue);
	if (( motorValue == readDshot() )&( commandIdleTime <= idleUpdateRateMicros )) {
		return;
	}
	commandIdleTime = 0;
	dshotThrottle(motorValue);

}

void adc0_isr(void) {
	if(samplerActive){ //last ADC request was from the sampler, grab the v/a
		ADCresult = adc->readSynchronizedSingle();

		sampleBuffer[sampleBufferIndex.write].voltsPresent = true;
		sampleBuffer[sampleBufferIndex.write].volts = (uint16_t)ADCresult.result_adc1;
		sampleBuffer[sampleBufferIndex.write].ampsPresent = true;
		sampleBuffer[sampleBufferIndex.write].amps = (uint16_t)ADCresult.result_adc0;

		sampleBuffer[sampleBufferIndex.write].ready = true;

		sampleBufferIndex.nextWrite();
		samplerActive = false;

		if (lastTempReadingTimer > 1){
			if ( tempEnable[tempIndex.write]){
				adc->adc0->startSingleRead(tempPins[tempIndex.write]);
			} else {
				tempIndex.nextWrite();
			}
			lastTempReadingTimer = 0;
		}
		//adc->adc0->readSingle(); // clear interrupt
	} else {
		//get the temp update
		tempValues[tempIndex.write]=(uint16_t)adc->adc0->readSingle();
		tempUpdate[tempIndex.write]=true;
		tempIndex.nextWrite();
	}
}

void setSamplerADCSettings(){
	//adc->setReference(ADC_REFERENCE::REF_3V3 , ADC_0);
	adc->setReference(ADC_REFERENCE::REF_EXT, ADC_0);
    adc->setAveraging(4, ADC_0); // set number of averages
    adc->setResolution(16, ADC_0); // set bits of resolution
    adc->setConversionSpeed(ADC_CONVERSION_SPEED::HIGH_SPEED_16BITS, ADC_0); // change the conversion speed
    adc->setSamplingSpeed(ADC_SAMPLING_SPEED::VERY_HIGH_SPEED   , ADC_0); // change the sampling speed

	//adc->setReference(ADC_REFERENCE::REF_3V3 , ADC_1);
	adc->setReference(ADC_REFERENCE::REF_EXT, ADC_1);
    adc->setAveraging(4, ADC_1); // set number of averages
    adc->setResolution(16, ADC_1); // set bits of resolution
    adc->setConversionSpeed(ADC_CONVERSION_SPEED::HIGH_SPEED_16BITS, ADC_1); // change the conversion speed
    adc->setSamplingSpeed(ADC_SAMPLING_SPEED::VERY_HIGH_SPEED   , ADC_1); // change the sampling speed

    adcMaxValue = adc->getMaxValue(ADC_0);

    adc->enableCompare(adcMaxValue, 0, ADC_0);
    adc->enableCompare(adcMaxValue, 0, ADC_1);
    //while (!adc->isComplete(ADC_0)){};
    //while (!adc->isComplete(ADC_1)){};

    correctionFactor = vRef/adcMaxValue;
}

void zeroSample(int index){
	sampleBuffer[index].ready = false;
	sampleBuffer[index].T1Present = false;
	sampleBuffer[index].T2Present = false;
	sampleBuffer[index].T3Present = false;
	sampleBuffer[index].T4Present = false;
	sampleBuffer[index].thrustPresent = false;
	sampleBuffer[index].commandValuePresent = false;
	sampleBuffer[index].tachPulsePresent = false;
	sampleBuffer[index].voltsPresent = false;
	sampleBuffer[index].ampsPresent = false;
}

void zeroSampleBuffers(){
	//zero out all of the sample buffers
	for (unsigned int i=0; i<MAXSAMPLES; i++ ) {
		zeroSample(i);
	}
}

void tachISR() {
	unsigned long time;
	time = tachTime;
	if (time < tachDebounce) return;
	if (tachCalibrated){
		tachCalibrationIndex.nextRead();
		lastTachPulse = time/tachCalibrationData[tachCalibrationIndex.read]; // compensate for partial rotation
		tachTime = tachTime - time; //reset the tach timer from when the initial time was captured
		tachUpdate = true;
	} else {
		tachPulseCount++;
		if (tachPulseCount < pulsesPerRev){
			return;
		} else {
			lastTachPulse = time ;
			tachTime = tachTime - time; //reset the tach timer from when the initial time was captured
			tachUpdate = true;
			tachPulseCount = 0;
		}
	}
}

void tachCalibrationISR() {
	unsigned long time;
	time = tachTime;
	if (time < tachDebounce) return;
	tachCalibrationIndex.nextRead();
	tachCalibrationTemp[tachCalibrationIndex.read] = time ;
	tachTime = tachTime - time; //reset the tach timer from when the initial time was captured

	tachPulseCount++;
	if (tachPulseCount >= pulsesPerRev){
		unsigned long totalPulse = 0;
		for(int i=0;i<pulsesPerRev;i++){
			totalPulse = totalPulse + tachCalibrationTemp[i];
			//Serial.println(tachCalibrationTemp[i]);

		}

		if (tachCalibrated){ //update calibration data with running averate
			//Serial.println("--");
			for(int i=0;i<pulsesPerRev;i++){
				float thisResult = (float)tachCalibrationTemp[i]/totalPulse;
				tachCalibrationData[i] = (thisResult + (tachCalibrationData[i] * tachCalibrationCount))/(tachCalibrationCount+1);
				//Serial.println(thisResult);
			}
		} else { //first full rotation, just load directly to calibration data
			//Serial.println(totalPulse);
			for(int i=0;i<pulsesPerRev;i++){
				float thisResult = (float)tachCalibrationTemp[i]/totalPulse;
				tachCalibrationData[i] = thisResult;
				//Serial.println(thisResult);
			}
			tachCalibrated = true;
			//Serial.println("done");
		}
		tachPulseCount = 0;
	}

}

void scaleISR() {
	//hacky trick to get around interrupt priority (tach and scale share port)
	//quickly fire off a low priority timer job that we can immediately end
	//when all high priority isrs have finished
	scaleUpdate.begin(scaleUpdateJob, 1);

}

void scaleUpdateJob() {
	scaleUpdate.end();
	detachInterrupt(HX_DAT_PIN); //kill the interrupt before we do any coms on the pin
	scaleUpdated = updateScaleValue();
	attachInterrupt(HX_DAT_PIN, scaleISR, FALLING);
}

void killScaleUpdateJobs() {
	//make sure all the scale jobs are dead
	scaleUpdate.end();
	detachInterrupt(HX_DAT_PIN); //kill the interrupt before we do any coms on the pin
}

void resetCommandBuffer(){
	//reset the entire command buffer
	for (unsigned int i=0; i<COMMANDBUFFER_SIZE; i++ ) {
		commandBuffer[i].mode = MODE_END;
		commandBuffer[i].time = 0;
		commandBuffer[i].value = 0;
		commandBuffer[i].useMicros = false;
	}
}

void checkTempSenors(){
	adc->setReference(ADC_REFERENCE::REF_3V3 , ADC_0);
    adc->setAveraging(32, ADC_0); // set number of averages
    adc->setResolution(16, ADC_0); // set bits of resolution
    adc->setConversionSpeed(ADC_CONVERSION_SPEED::HIGH_SPEED_16BITS, ADC_0); // change the conversion speed
    adc->setSamplingSpeed(ADC_SAMPLING_SPEED::HIGH_SPEED  , ADC_0); // change the sampling speed

	adc->setReference(ADC_REFERENCE::REF_3V3 , ADC_1);
    adc->setAveraging(32, ADC_1); // set number of averages
    adc->setResolution(16, ADC_1); // set bits of resolution
    adc->setConversionSpeed(ADC_CONVERSION_SPEED::HIGH_SPEED_16BITS, ADC_1); // change the conversion speed
    adc->setSamplingSpeed(ADC_SAMPLING_SPEED::HIGH_SPEED  , ADC_1); // change the sampling speed

    adc->enableCompare(adcMaxValue, 0, ADC_0);
    adc->enableCompare(adcMaxValue, 0, ADC_1);
    //while (!adc->isComplete(ADC_0)){};
    //while (!adc->isComplete(ADC_1)){};
    adcMaxValue = adc->getMaxValue(ADC_0);

    correctionFactor = 3.3/adcMaxValue;

	for (unsigned int i=0; i<4; i++ ) {
		rawTemp = (uint16_t)adc->analogRead(tempPins[i]);
		if( (rawTemp*correctionFactor) > 3.0 ){
			tempEnable[i]=false;
			Serial.print("disabling ");
			Serial.println(i);
		} else {
			tempEnable[i]=true;
			Serial.print("enabling ");
			Serial.println(i);

		}
	}

}

void getSample(){
	unsigned long time;

	//check if we're sitting in an overflow state and dump the sample if needed
	if (sampleBufferIndex.isFull()) {
		overrunS++;
		return;
	}

	//record the current time for the start of the sample
	time = testTime;
	// do some ADC reads
	samplerActive = true;
    adc->startSynchronizedSingleRead(ISENSE_PIN, VSENSE_PIN);

	// check the loadcell for updates

    sampleBuffer[sampleBufferIndex.write].time = time;

	if (scaleUpdated){
		scaleUpdated = false;
		sampleBuffer[sampleBufferIndex.write].thrustPresent = true;
		sampleBuffer[sampleBufferIndex.write].thrust = scaleValue;
	}

	if (getDshotUpdated()){
		resetDshotUpdated();
		//make note of the current command micros for the ESC
		sampleBuffer[sampleBufferIndex.write].commandValuePresent = true;
		//sampleBuffer[sampleBufferIndex.write].commandValue = ESC.readMicroseconds();
		sampleBuffer[sampleBufferIndex.write].commandValue = readDshot();
	}

	//RPM
	if(tachUpdate){
		tachUpdate = false;
		sampleBuffer[sampleBufferIndex.write].tachPulsePresent = true;
		sampleBuffer[sampleBufferIndex.write].tachPulse = lastTachPulse;
	}

	//temp probes
	if(tempUpdate[0]){
		tempUpdate[0] = false;
		sampleBuffer[sampleBufferIndex.write].T1Present = true;
		sampleBuffer[sampleBufferIndex.write].T1 = tempValues[0];
	}
	if(tempUpdate[1]){
		tempUpdate[1] = false;
		sampleBuffer[sampleBufferIndex.write].T2Present = true;
		sampleBuffer[sampleBufferIndex.write].T2 = tempValues[1];
	}
	if(tempUpdate[2]){
		tempUpdate[2] = false;
		sampleBuffer[sampleBufferIndex.write].T3Present = true;
		sampleBuffer[sampleBufferIndex.write].T3 = tempValues[2];
	}
	if(tempUpdate[3]){
		tempUpdate[3] = false;
		sampleBuffer[sampleBufferIndex.write].T4Present = true;
		sampleBuffer[sampleBufferIndex.write].T4 = tempValues[3];
	}
}

void getCSVLine(char* str){
	float volts;
	float amps;
	float RPM = 0;
	float temperatureValue = 0;
	char temp[80];


    volts = getVolts( sampleBuffer[sampleBufferIndex.read].volts );
    amps = getAmps( sampleBuffer[sampleBufferIndex.read].amps );

	//format the CSV line
	sprintf(temp, "%lu,%i", sampleBuffer[sampleBufferIndex.read].time, sampleBuffer[sampleBufferIndex.read].commandValue);

	strcat(str, temp);

	if (sampleBuffer[sampleBufferIndex.read].tachPulsePresent){
		RPM = ((1000000.0/sampleBuffer[sampleBufferIndex.read].tachPulse)/pulsesPerRev )*60;

		sprintf(temp, ",%.3f", RPM);
		strcat(str, temp);
	}else {
		strcat(str, ",");

	}

	sprintf(temp, ",%.3f,%.3f",  volts, amps);
	strcat(str, temp);

	if (sampleBuffer[sampleBufferIndex.read].thrustPresent){
		sprintf(temp, ",%.2f\n", sampleBuffer[sampleBufferIndex.read].thrust);

		strcat(str, temp);

	}else {
		strcat(str, ",");

	}

	for (unsigned int i=0; i<4; i++ ) {
		if (tempUpdate[i]){
			tempUpdate[i]=false;
			temperatureValue = getTemp(tempValues[0]);
			sprintf(temp, ",%.2f", temperatureValue);
			strcat(str, temp);
		}else {
			strcat(str, ",");

		}
	}



	strcat(str, "\n");

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

void runSerialCommand(){

	if (strncmp (serialCommand,"test",strlen("test")) == 0) {
		Serial.println("got test");
		testFunc();
	} else if (strncmp (serialCommand,"run",strlen("run")) == 0) {

		Serial.println("got run");
		char* fileString = serialCommand + strlen("run");
		if(strlen(fileString)){
			loadProgram(fileString);
		} else {
			loadProgram("program.txt");
		}

		doTestLog();
	} else if (strncmp (serialCommand,"list",strlen("list")) == 0) {
		Serial.println("got list");

	} else if (strncmp (serialCommand,"runprog",strlen("runprog")) == 0) {
		Serial.println("got runprog");
		char* fileString = serialCommand + strlen("runprog");
		Serial5.print(fileString);
		Serial5.print(" ");
		Serial5.println(strlen(fileString));

	}

	memset(serialCommand, 0, 256);
	serialCommandIndex = 0;
}

void handleSerialCommandInput(){
    if (Serial5.available()) {
    	sChar = Serial5.read();
    	if (scReading){
			if (sChar == '>') {
				scReading = false;
				runSerialCommand();
			} else {
				if (serialCommandIndex < 255){
					serialCommand[serialCommandIndex]=sChar;
					serialCommandIndex++;
				}
			}
    	} else {
			if (sChar == '<') {
				scReading = true;
			}
    	}
	}
}

void loop() {
	//dump anything sitting in the serial buffer
	while (Serial.read() >= 0) {}
	Serial.println();

	Serial.println(F("type:"));
	Serial.println(F("r - run"));
	Serial.println(F("t - test"));

	//spin while waiting for user input
	while(!Serial.available()) {
		handleSerialCommandInput();
	}

		/*buttonHandler();
		if (buttonDown){
			buttonDown = false;
			doTestLog();
			return;
		}*/


	char c = tolower(Serial.read());

	// Discard extra Serial data.
	do {
	delay(10);
	} while (Serial.read() >= 0);

	if (c == 'r') {
		loadProgram("program.txt");
		doTestLog();
	} else 	if (c == 't') {
	  testFunc();
	} else 	if (c == 'e') {
		Serial5.println("Serial Echo");
		Serial.println("Serial Echo");
	}  else {
	Serial.println(F("Invalid entry"));
	}

}

void testFunc() {

	checkTempSenors();
	pinMode(LED_PIN, OUTPUT);
	setSamplerADCSettings();
	elapsedMicros dtime;
	dtime=0;
	while(true){
		if (tempEnable[0]) {
			uint16_t rawTemp = (uint16_t)adc->analogRead(tempPins[0]);
			float temp = getTemp(rawTemp);
			Serial.println(temp);

		}
		//if( (rawTemp*correctionFactor) > 3.0 ){

		while (dtime<10000){};
		dtime=0;
	}


	while(true){
		//dshotThrottle(1046);
		digitalWriteFast(LED_PIN, 1);
		dshotOut(1046);
		digitalWriteFast(LED_PIN, 0);

		while (dtime<100000){};
		dtime=0;
	}

	commandTrigger.priority(180);
	commandTrigger.begin(testISR, 3000); // start logger

	//dshotOut(48);

    //adc->enableCompare(1.0/2.5*adc->getMaxValue(ADC_0), 0, ADC_0);
    //adc->enableCompare(1.0/2.5*adc->getMaxValue(ADC_1), 0, ADC_1);
    //while (!adc->isComplete(ADC_0)){};
    //while (!adc->isComplete(ADC_1)){};
    //adcMaxValue = adc->getMaxValue(ADC_0);

    correctionFactor = 3.3/adcMaxValue;

    uint16_t raw;
    /*
	for (int i; i<800; i++){
		setWiper(i+100);
	    raw = (uint16_t)adc->analogRead(TACH_PIN_A);
		Serial.print(i+100);
		Serial.print(" ");
		Serial.println(raw*correctionFactor);

	}

	Serial.print("value ");
	Serial.println(readWiper());
	*/


	//Serial5.print("value ");
	//Serial5.println(readWiper());
	//digitalWrite(BATTERY_SENSE, 1);
	//digitalWrite(RANGE_3S , 1);
	//digitalWrite(RANGE_4S , 1);
	//digitalWrite(RANGE_5S , 1);


	  //delay(500);

	/*

	digitalWrite(CALIBRATION_SENSE , 1);
	rawTemp = (uint16_t)adc->analogRead(T1_PIN);
	Serial.print("T1 ");
	Serial.println(rawTemp*correctionFactor);
	rawTemp = (uint16_t)adc->analogRead(T2_PIN);
	Serial.print("T2 ");
	Serial.println(rawTemp*correctionFactor);
	rawTemp = (uint16_t)adc->analogRead(T3_PIN);
	Serial.print("T3 ");
	Serial.println(rawTemp*correctionFactor);
	rawTemp = (uint16_t)adc->analogRead(T4_PIN);
	Serial.print("T4 ");
	Serial.println(rawTemp*correctionFactor);
	rawTemp = (uint16_t)adc->analogRead(VSENSE_PIN);
	Serial.print("vsense ");
	Serial.println(rawTemp*correctionFactor);
	rawTemp = (uint16_t)adc->analogRead(ISENSE_PIN);
	Serial.print("I1 ");
	Serial.println(rawTemp*correctionFactor);
	rawTemp = (uint16_t)adc->analogRead(ISENSE2_PIN);
	Serial.print("I2 ");
	Serial.println(rawTemp*correctionFactor);
	rawTemp = (uint16_t)adc->analogRead(TREF_PIN);
	Serial.print("Tref ");
	Serial.println(getTMP35Temp(rawTemp));

	*/

	//digitalWrite(CALIBRATION_SENSE , 1);
	//digitalWrite(RANGE_3S , 1);
	//digitalWrite(RANGE_4S , 1);
	//digitalWrite(RANGE_5S , 1);


}

void doTestLog() {
	Serial.println("type s to end");
	char c;
	uint16_t sampleMask = 0;

	digitalWrite(LED_PIN, 0);

	loadConfig();
	//loadProgram();
	zeroSampleBuffers();
	sampleBufferIndex.reset();
	overrunS = 0;
	maxSampleBuffer = 0;
	char str[80];

	if (!sd.begin()) sd.initErrorHalt("SdFatSdioEX begin failed");
	sd.chvol();

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

	abortReason = ABORT_NONE;

	tachCalibrated = false;
	tachCalibrationIndex.reset();
	tachPulseCount = 0;

	checkTempSenors();
	setSamplerADCSettings();
	digitalWrite(CALIBRATION_SENSE, 0);
	digitalWrite(BATTERY_SENSE, 1);

	logHead();

	// start the log sampling ISR
	attachInterrupt(TACH_PIN, tachISR, tachTriggerType);
	tachTime = 0;
	lastTachPulse = 1000000/( (1.0/60) *pulsesPerRev); //start tach at 1 rpm

	// start the load cell ADC
	scaleISR();

	//startup the ADC so it's ready to read on the first sample
    adc->enableInterrupts();

    idler.end();

	testTime = 0; //reset the master timer
	logSampler.begin(getSample, sampleRateMicros); // start logger
	runCurrentCommand();

	bool running = true;

	// start spinning on the ring buffer, writing to disk as soon as each block fills
	while(running){
		maxSampleBuffer = max( sampleBufferIndex.getFillLength(), maxSampleBuffer);


		while ( sampleBufferIndex.getFillLength() > 0  ){
			maxSampleBuffer = max( sampleBufferIndex.getFillLength(), maxSampleBuffer);
			//memset(str, 0, 80);

			/*
			str[0] = 0;
			getCSVLine(str);
			if (!file.write(str) ) {
				Serial.println("write data failed");
			}
			*/


			ringIndexManager byteIndex(32);
			byteIndex.reset();
			// advance by 2 to leave room for bitmask
			byteIndex.nextWrite();
			byteIndex.nextWrite();

			byteMap convert;
			uint8_t allSample[28];
			sampleMask = 0;

			sampleMask |= SAMPLE_TIME;
			convert.ulong = sampleBuffer[sampleBufferIndex.read].time;
			allSample[byteIndex.write]=convert.uint8[0];
			byteIndex.nextWrite();
			allSample[byteIndex.write]=convert.uint8[1];
			byteIndex.nextWrite();
			allSample[byteIndex.write]=convert.uint8[2];
			byteIndex.nextWrite();
			allSample[byteIndex.write]=convert.uint8[3];
			byteIndex.nextWrite();

			if (sampleBuffer[sampleBufferIndex.read].commandValuePresent){
				sampleMask |= SAMPLE_MOTORCOMMAND;
				convert.i[0] = sampleBuffer[sampleBufferIndex.read].commandValue;
				allSample[byteIndex.write]=convert.uint8[0];
				byteIndex.nextWrite();
				allSample[byteIndex.write]=convert.uint8[1];
				byteIndex.nextWrite();
			}

			if (sampleBuffer[sampleBufferIndex.read].tachPulsePresent){
				sampleMask |= SAMPLE_TACH;
				convert.ulong = sampleBuffer[sampleBufferIndex.read].tachPulse;
				allSample[byteIndex.write]=convert.uint8[0];
				byteIndex.nextWrite();
				allSample[byteIndex.write]=convert.uint8[1];
				byteIndex.nextWrite();
				allSample[byteIndex.write]=convert.uint8[2];
				byteIndex.nextWrite();
				allSample[byteIndex.write]=convert.uint8[3];
				byteIndex.nextWrite();
			}

			sampleMask |= SAMPLE_VOLT;
			convert.uint16[0] = sampleBuffer[sampleBufferIndex.read].volts;
			allSample[byteIndex.write]=convert.uint8[0];
			byteIndex.nextWrite();
			allSample[byteIndex.write]=convert.uint8[1];
			byteIndex.nextWrite();

			sampleMask |= SAMPLE_AMP;
			convert.uint16[0] = sampleBuffer[sampleBufferIndex.read].amps;
			allSample[byteIndex.write]=convert.uint8[0];
			byteIndex.nextWrite();
			allSample[byteIndex.write]=convert.uint8[1];
			byteIndex.nextWrite();

			if (sampleBuffer[sampleBufferIndex.read].thrustPresent){
				sampleMask |= SAMPLE_THRUST;
				convert.flt = sampleBuffer[sampleBufferIndex.read].thrust;
				allSample[byteIndex.write]=convert.uint8[0];
				byteIndex.nextWrite();
				allSample[byteIndex.write]=convert.uint8[1];
				byteIndex.nextWrite();
				allSample[byteIndex.write]=convert.uint8[2];
				byteIndex.nextWrite();
				allSample[byteIndex.write]=convert.uint8[3];
				byteIndex.nextWrite();
			}

			if (sampleBuffer[sampleBufferIndex.read].T1Present){
				sampleMask |= SAMPLE_T1;
				convert.uint16[0] = sampleBuffer[sampleBufferIndex.read].T1;
				allSample[byteIndex.write]=convert.uint8[0];
				byteIndex.nextWrite();
				allSample[byteIndex.write]=convert.uint8[1];
				byteIndex.nextWrite();
			}

			if (sampleBuffer[sampleBufferIndex.read].T2Present){
				sampleMask |= SAMPLE_T2;
				convert.uint16[0] = sampleBuffer[sampleBufferIndex.read].T2;
				allSample[byteIndex.write]=convert.uint8[0];
				byteIndex.nextWrite();
				allSample[byteIndex.write]=convert.uint8[1];
				byteIndex.nextWrite();
			}

			if (sampleBuffer[sampleBufferIndex.read].T3Present){
				sampleMask |= SAMPLE_T3;
				convert.uint16[0] = sampleBuffer[sampleBufferIndex.read].T3;
				allSample[byteIndex.write]=convert.uint8[0];
				byteIndex.nextWrite();
				allSample[byteIndex.write]=convert.uint8[1];
				byteIndex.nextWrite();
			}

			if (sampleBuffer[sampleBufferIndex.read].T4Present){
				sampleMask |= SAMPLE_T4;
				convert.uint16[0] = sampleBuffer[sampleBufferIndex.read].T4;
				allSample[byteIndex.write]=convert.uint8[0];
				byteIndex.nextWrite();
				allSample[byteIndex.write]=convert.uint8[1];
				byteIndex.nextWrite();
			}

			//fill in the bitmask
			convert.uint16[0] = sampleMask;
			allSample[0]=convert.uint8[0];
			allSample[1]=convert.uint8[1];


			if (!file.write(allSample, byteIndex.write) ) {
				Serial.println("write data failed");
			}

			zeroSample(sampleBufferIndex.read);
			sampleBufferIndex.nextRead();
			/*
			writeBufferIndex.nextWrite();

			if (!file.write(writeBuffer[writeBufferIndex.read].data, strlen(writeBuffer[writeBufferIndex.read].data))) {
				Serial.println("write data failed");
			}
			memset(writeBuffer[writeBufferIndex.read].data, 0, BUFFERSIZE+1);
			// mark it as available in the ringbuffer
			writeBuffer[writeBufferIndex.read].full = false;
			writeBufferIndex.nextRead();
			*/

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
			// reset the ESC and kill the command ISR
			//ESC.writeMicroseconds(1000);
			commandTrigger.end();
			idler.begin(idleISR, idleUpdateRateMicros);

			//reset the command program to the beginning
			commandIndex=0;
			// kill the log sampling ISR
			logSampler.end();
			// kill the tach ISR
			detachInterrupt(TACH_PIN);
			// kill the load cell ISR
			killScaleUpdateJobs();
			//add any tail info to the log file
			logTail();

			Serial.print("longest loop ");
			Serial.print(longestLoop);
			Serial.print("/");
			Serial.print(sampleRateMicros);
			Serial.print(" ");
			Serial.println((float)longestLoop/sampleRateMicros);
			Serial.print("loop idle ");
			Serial.print(idleTimeMin);
			Serial.print("/");
			Serial.println(idleTimeMax);
			Serial.print("max samples ");
			Serial.println(maxSampleBuffer);
			if (overrunS > 0) {
				Serial.print("overS ");
				Serial.println(overrunS);
			}
			file.flush();
			file.close();
			running = false;

		}

	}

	Serial.println("log completed");
	digitalWrite(LED_PIN, 1);

}

void logHead(){
	float ambientTemp;
	char str[80];

    adc->setAveraging(32, ADC_0); // set number of averages
	rawTemp = (uint16_t)adc->analogRead(T1_PIN, ADC_0);
    adc->setAveraging(2, ADC_0); // set number of averages

    ambientTemp = getTemp(rawTemp);

	file.write("log version: 2\n");
	sprintf(str, "ambient temp: %.1f\n", ambientTemp );
	file.write(str);
	sprintf(str, "pulse per rev: %i\n", pulsesPerRev );
	file.write(str);
	sprintf(str, "loadcell calibration value: %.2f\n", scaleCalibrationValue );
	file.write(str);
	sprintf(str, "command update rate: %i\n", commandUpdateRate );
	file.write(str);
	sprintf(str, "adcMaxValue: %i\n", adcMaxValue );
	file.write(str);
	sprintf(str, "thermBValue: %i\n", thermBValue );
	file.write(str);
	sprintf(str, "vref: %.2f\n", vRef );
	file.write(str);
	file.write("motor: \n");
	file.write("ESC: \n");
	file.write("settings: \n");
	file.write("firmware: \n");
	file.write("prop: \n");
	file.write("power: \n");
	file.write("\n");

	file.write("Time,Motor Command,RPM,Volt,Amp,Thrust,T1,T2,T3,T4\n");
	file.write("Data Start:\n");

}

void logTail(){
	//file.write("\n");

	switch (abortReason){
	case ABORT_NONE:
		break;
	case ABORT_TESTEND:
		break;
	case ABORT_USER:
		file.write("Test aborted: user request");
		break;
	case ABORT_DANGER:
		file.write("Test aborted: emergency stop condition");
		break;
	}
}

void createLogFile(const char logfile[]){
	Serial.print("opening file ");
	Serial.println(logfile);

	if (!file.open(logfile, O_WRITE | O_CREAT)) {
		Serial.print("open failed");
	  }

	return;
}

float getTemp(const float rawValue){
	// convert raw ADC reading into temperature in degrees C


	//Thermistor B value calc for 10k nominal, result in K
	// temp = 1/( ( 1/298.15 ) + LOG(resistance/10000)/B )
	//convert K to C
	// C = K - 273.15

	//get absolute voltage
	float rawVolt = rawValue*correctionFactor;

	float r = rawVolt/0.0001;

	float kValue = 1/( ( 1/298.15 ) + log(r/10000)/thermBValue );
	float cValue = kValue - 273.15;
	return cValue;
}

float getTMP35Temp(const float rawValue){
	// convert raw ADC reading into temperature in degrees C

	//get absolute voltage
	float rawVolt = rawValue*correctionFactor;
	//get temperature from voltage

	//TMP36
	//double cValue = ((rawVolt - .750)*100) + 24;
	//TMP35
	float cValue = ((rawVolt - .250)*100) + 24;
	return cValue;
}

float getVolts(const float rawValue){
	// convert raw ADC reading into battery voltage


	//get absolute voltage
	float rawVolt = rawValue*correctionFactor;

	//AttoPilot 90A sensor
	float vValue = rawVolt*(1.0/0.06369) ;

	//allegro 100a divider values
	// 25.44/1.278   total 26.72
	//double vValue = rawVolt / (1.278/26.72 ) ;

	//vValue = vValue * 1.327;
	return vValue;
}

float getAmps(const float rawValue){
	// convert raw ADC reading into battery voltage


	//get absolute voltage
	float rawVolt = rawValue*correctionFactor;

	//AttoPilot 90A sensor
	float aValue = rawVolt*(1.0/0.0366) ;

	//allegro 100a divider values
	// 20mv/A ,  0amp point 1/2 supply voltage
	//2.175 / 6.71  total 8.89
	//double sensorValue = rawVolt / (6.71/8.89) ;
	//double offset = (3.76 / 2.0);
	//double aValue = (sensorValue-offset) * (1.0/0.02 ) ;

	//aValue = ( aValue - 33.5 )*3.3
	return aValue;
}

void setupLoadCell() {
	// TODO: calibration
	scale.set_scale(scaleCalibrationValue);          // this value is obtained by calibrating the scale with known weights;
	tare();
}

void tare() {
	scale.tare(8);				        // reset the scale to 0, 8 samples average
}

void powerScale() {
	// nothing going on here yet
	scale.power_down();			        // put the ADC in sleep mode
	scale.power_up();
}

bool updateScaleValue() {
	// update the global measurement value, but only if the scale is ready to be read
	if (scale.is_ready()){
		scaleValue = scale.get_units();
		return true;
	}
	return false;
}

void setCommandUpdateRate(uint16_t rate){
	commandUpdateRate = rate; // ESC update in hz
	commandUpdateRateMicros = (1.0/commandUpdateRate)*1000000;
}

void setSampleRate(uint16_t rate){
	sampleRate = rate; // log sampler rate in hz
	sampleRateMicros = (1.0/sampleRate)*1000000;
}

int endsWith(const char *str, const char *suffix)
{
    if (!str || !suffix)
        return 0;
    size_t lenstr = strlen(str);
    size_t lensuffix = strlen(suffix);
    if (lensuffix >  lenstr)
        return 0;
    return strncmp(str + lenstr - lensuffix, suffix, lensuffix) == 0;
}

void loadConfig() {
	if (!sd.begin()) sd.initErrorHalt("SdFatSdioEX begin failed");
	sd.chvol();

	  const int line_buffer_size = 256;
	  char buffer[line_buffer_size];

	  char * propertyValue;
	  float value;

	  ifstream sdin("config.txt");
      Serial.println("loading config");

	  while (sdin.getline(buffer, line_buffer_size, '\n') || sdin.gcount()) {
		  propertyValue=strchr(buffer,':');
		  if (propertyValue!=NULL) propertyValue++;

		  if (strncmp (buffer,"commandUpdateRate",strlen("commandUpdateRate")) == 0)
		    {
			  if (propertyValue==NULL) continue;
			  value = atof(propertyValue);
		      Serial.println("setting commandUpdateRate");
		      setCommandUpdateRate( (uint16_t)value );
		      continue;
		    }
		  if (strncmp (buffer,"sampleRate",strlen("sampleRate")) == 0)
		    {
			  if (propertyValue==NULL) continue;
			  value = atof(propertyValue);
		      Serial.println("setting sampleRate");
		      setSampleRate( (uint16_t)value );
		      continue;
		    }
		  if (strncmp (buffer,"tachTrigger",strlen("tachTrigger")) == 0)
		    {
			  if (propertyValue==NULL) continue;
			  if (strncmp (propertyValue,"FALLING",strlen("FALLING")) == 0)
			  {
				  value = FALLING;
			  } else if (strncmp (propertyValue,"CHANGE",strlen("CHANGE")) == 0)
			  {
				  value = CHANGE;
			  } else
			  {
				  value = RISING;
			  }
		      tachTriggerType = value;
		      Serial.print("setting tach trigger type ");
		      Serial.println(tachTriggerType);
		      continue;
		    }		  
		  if (strncmp (buffer,"tachPulsePerRev",strlen("tachPulsePerRev")) == 0)
		    {
			  if (propertyValue==NULL) continue;
			  value = atof(propertyValue);
		      pulsesPerRev = (uint8_t)value;
		      tachCalibrationIndex = ringIndexManager(pulsesPerRev);
		      Serial.print("setting tachPulsePerRev ");
		      Serial.println(pulsesPerRev);

		      continue;
		    }
		  if (strncmp (buffer,"tachDebounce",strlen("tachDebounce")) == 0)
		    {
			  if (propertyValue==NULL) continue;
			  value = atof(propertyValue);
		      tachDebounce = (uint16_t)value;
		      Serial.print("setting tachDebounce ");
		      Serial.println(tachDebounce);
		      continue;
		    }
		  if (strncmp (buffer,"thermBValue",strlen("thermBValue")) == 0)
		    {
			  if (propertyValue==NULL) continue;
			  value = atof(propertyValue);
			  thermBValue = (uint16_t)value;
		      Serial.print("setting thermBValue ");
		      Serial.println(thermBValue);
		      continue;
		    }
		  if (strncmp (buffer,"loadCellCalibration",strlen("loadCellCalibration")) == 0)
		    {
			  if (propertyValue==NULL) continue;
			  value = atof(propertyValue);
		      Serial.println("setting loadCellCalibration");
		      scaleCalibrationValue = value;
		      setupLoadCell();
		      continue;
		    }
	  }

	  sdin.close();
}


void loadProgram(char * filename) {
	if (!sd.begin()) sd.initErrorHalt("SdFatSdioEX begin failed");
	sd.chvol();

		const int line_buffer_size = 256;
		char buffer[line_buffer_size];

		char * propertyValue;
		char * tokenPtr;

		unsigned long cTime = 0;
		float cValue = 0;
		bool cUseMicros = false;

		Serial5.print("loading program ");
		Serial5.println(filename);
		ifstream sdin(filename);

		resetCommandBuffer();
		unsigned int bufferIndex = 0;

	  while (sdin.getline(buffer, line_buffer_size, '\n') || sdin.gcount()) {
		  if (bufferIndex >= COMMANDBUFFER_SIZE-1) break; //drop commands if there are too many, always leave room for the end test command.
		  propertyValue=strchr(buffer,' ');
		  if (propertyValue!=NULL) propertyValue++;

		  if (strncmp (buffer,"ramp",strlen("ramp")) == 0)
		    {
			  if (propertyValue==NULL) continue;
			  tokenPtr = strtok( propertyValue, " ");
			  if (tokenPtr==NULL) continue;
			  cValue = atof(tokenPtr);
			  tokenPtr = strtok( NULL, " ");
			  if (tokenPtr==NULL) continue;
			  cTime = strtoul(tokenPtr, NULL, 0);

			  if ( endsWith(tokenPtr,"us") ){
				cUseMicros = true;
			  } else if ( endsWith(tokenPtr,"ms") ){
				cUseMicros = false;
			  } else { //assume s
				cUseMicros = false;
				cTime = cTime * 1000;
			  }
				commandBuffer[bufferIndex].mode = MODE_RAMP;
				commandBuffer[bufferIndex].time = cTime;
				commandBuffer[bufferIndex].value = 1999*(cValue/100)+1;
				commandBuffer[bufferIndex].useMicros = cUseMicros;
				bufferIndex++;
		      continue;
		  }
		  if (strncmp (buffer,"hold",strlen("hold")) == 0)
		    {
			  if (propertyValue==NULL) continue;
			  tokenPtr = strtok( propertyValue, " ");
			  if (tokenPtr==NULL) continue;
			  cValue = atof(tokenPtr);
			  tokenPtr = strtok( NULL, " ");
			  if (tokenPtr==NULL) continue;
			  cTime = strtoul(tokenPtr, NULL, 0);

			  if ( endsWith(tokenPtr,"us") ){
				cUseMicros = true;
			  } else if ( endsWith(tokenPtr,"ms") ){
				cUseMicros = false;
			  } else { //assume s
				cUseMicros = false;
				cTime = cTime * 1000;
			  }
				commandBuffer[bufferIndex].mode = MODE_HOLD;
				commandBuffer[bufferIndex].time = cTime;
				//commandBuffer[bufferIndex].value = 1000 + (1000*(cValue/100));
				commandBuffer[bufferIndex].value = 1999*(cValue/100)+1;
				commandBuffer[bufferIndex].useMicros = cUseMicros;
				bufferIndex++;
		      continue;
		    }
		  if (strncmp (buffer,"tach",strlen("tach")) == 0)
		    {
			  if (propertyValue==NULL) continue;
			  tokenPtr = strtok( propertyValue, " ");
			  if (tokenPtr==NULL) continue;
			  cValue = atof(tokenPtr);
			  tokenPtr = strtok( NULL, " ");
			  if (tokenPtr==NULL) continue;
			  cTime = strtoul(tokenPtr, NULL, 0);

			  if ( endsWith(tokenPtr,"us") ){
				cUseMicros = true;
			  } else if ( endsWith(tokenPtr,"ms") ){
				cUseMicros = false;
			  } else { //assume s
				cUseMicros = false;
				cTime = cTime * 1000;
			  }
				commandBuffer[bufferIndex].mode = MODE_TACH;
				commandBuffer[bufferIndex].time = cTime;
				//commandBuffer[bufferIndex].value = 1000 + (1000*(cValue/100));
				commandBuffer[bufferIndex].value = 1999*(cValue/100)+1;
				commandBuffer[bufferIndex].useMicros = cUseMicros;
				bufferIndex++;
		      continue;
		    }
		  if (strncmp (buffer,"tare",strlen("tare")) == 0)
		    {
				commandBuffer[bufferIndex].mode = MODE_TARE;
				commandBuffer[bufferIndex].time = 0;
				commandBuffer[bufferIndex].value = 0;
				commandBuffer[bufferIndex].useMicros = false;
				bufferIndex++;
				continue;
		    }
	  }

	  sdin.close();
}
