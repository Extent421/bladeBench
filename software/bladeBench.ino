#include "bladeBench.h"
#include "pins.h"
#include "ringIndexManager.h"
#include "ad5272.h"
#include "dshot.h"
#include "util.h"

#include <string.h>
#include <stdio.h>

#include "Servo.h"

#include <SPI.h>
#include <SdFat.h>
#include <ADC.h>
#include <i2c_t3.h>

// File system object.
SdFatSdioEX sd;

// Log file.
File file;

// adc object
ADC *adc = new ADC();
ADC::Sync_result ADCresult;

float scaleCalibrationValue = 117973.4857;
long tareValue = 0;
long scaleValue;
volatile bool scaleUpdated = false;

Servo ESC;
Servo AUX;

IntervalTimer logSampler;
IntervalTimer commandTrigger;
IntervalTimer idler;

uint16_t adcMaxValue = 0;
float vRef = 3;

float rawTemp;
float rawVolt;
float cValue;
float correctionFactor = 2.5/pow(2,16); // ADC to volt. 2.5v external reference

vCalibration vCalibrate;

//double loopCount = 0;
uint16_t bounceCount = 0;
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
float tachCalibrationTemp[10];
ringIndexManager tachCalibrationIndex(2);
volatile bool tachCalibrated = 0;
volatile bool tachCalibrateRunning = 0;
uint16_t tachCalibrationCount = 0;

uint8_t ADCAveraging = 4;

bool abortTest = false;
uint8_t abortReason = ABORT_NONE;


float motorValue=0;
float auxValue=0;

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

uint16_t idleUpdateRate = 200; // ESC update in hz  Dshot timeout is 200hz
uint32_t idleUpdateRateMicros = (1.0/idleUpdateRate)*1000000;
elapsedMicros commandIdleTime;

uint16_t auxCommandRate = 50; // Aux servo update in hz
uint32_t auxCommandRateMicros = (1.0/auxCommandRate)*1000000;
uint16_t auxMinUsec = 1000;
uint16_t auxMaxUsec = 1500;



uint16_t sampleRate = 1000; // log sampler rate in hz
uint32_t sampleRateMicros = (1.0/sampleRate)*1000000;

uint16_t tempShutdownValue = 0;

volatile bool samplerActive = false;
volatile bool loadSamplerActive = false;


command commandBuffer[COMMANDBUFFER_SIZE];
volatile uint8_t commandIndex = 0;
float commandIncrement = 0; //number of microseconds to increment the servo object each command loop
float command2Increment = 0; //number of microseconds to increment the servo object each command loop
unsigned long commandMicros = 0; //number of microseconds to run the current command for

char* loadedProgram;

char sChar;
char serialCommand[256];
int serialCommandIndex = 0;
bool scReading = false;

bool useDshot = false;


void setup() {


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
	pinMode(ESC_PIN, OUTPUT);
	digitalWrite(ESC_PIN, 0);

	pinMode(AUXSERVO_PIN, OUTPUT);
	digitalWrite(AUXSERVO_PIN, 0);

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
	//while (!Serial) {	}

	Serial.println("starting up");
	Serial5.begin(115200);

	if (!sd.begin()) {
		Serial.println("SdFatSdioEX begin failed");
	}
	sd.chvol();

	setSamplerADCSettings();

	logSampler.priority(200); // set lowish priority.  We want to let regular fast ISRs (like servo timing) to be able to interrupt


	//setupLoadCell();

	Wire2.begin(I2C_MASTER, 0x00, I2C_PINS_3_4, I2C_PULLUP_EXT, 400000);
	Wire2.setDefaultTimeout(10000); // 10ms
	enableWiper();
	setWiper(350);

	memset(serialCommand, 0, 256);

	if(useDshot){
		setupDshotDMA();
	} else {
		ESC.attach(ESC_PIN, 125, 250);  // attaches the servo on pin 9 to the servo object as oneshot protocol
		ESC.setRefreshUsec(2000);
		ESC.writeCommand(0);
	}

	idler.begin(idleISR, idleUpdateRateMicros);

	pinMode(LED_PIN, OUTPUT);
	digitalWrite(LED_PIN, 1);
	Serial.println();

	Serial.println(F("ready"));


}

void loop() {

	handleSerialCommandInput();

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
		commandTrigger.end();
		logSampler.end();

		idler.begin(idleISR, idleUpdateRateMicros);

		commandIndex=0;
		abortTest=true;
		abortReason = ABORT_TESTEND;
		break;
	case MODE_RAMP:
		// reset the command timer
		commandTime = 0;

		// grab the total length of the command
		if (commandBuffer[commandIndex].useMicros){
			commandMicros = commandBuffer[commandIndex].time;
		} else {
			commandMicros = commandBuffer[commandIndex].time * 1000;
		}
		// pre-calculate the ESC increment for each command loop
		if (useDshot) {
			commandValue = readDshot();
		} else {
			commandValue = ESC.readCommand();
		}
		motorValue = commandValue;
		updateCount = commandMicros/commandUpdateRateMicros;
		commandIncrement = (float)(commandBuffer[commandIndex].value - commandValue)/updateCount;
		if (commandBuffer[commandIndex].value2 > -1) {
			command2Increment = (float)((auxMinUsec + (commandBuffer[commandIndex].value2/2000.0)*(auxMaxUsec-auxMinUsec)) - auxValue)/updateCount;
		}

		// kick off the command loop
		commandTrigger.begin(commandISR, commandUpdateRateMicros);
		break;
	case MODE_HOLD:
		commandTime = 0;

		if (commandBuffer[commandIndex].useMicros){
			commandMicros = commandBuffer[commandIndex].time;
		} else {
			commandMicros = commandBuffer[commandIndex].time * 1000;
		}
		commandTrigger.begin(commandISR, commandUpdateRateMicros);
		commandIncrement = 0;
		motorValue = commandBuffer[commandIndex].value;
		if (commandBuffer[commandIndex].value2 > -1) {
			auxValue = auxMinUsec + (commandBuffer[commandIndex].value2/2000.0)*(auxMaxUsec-auxMinUsec) ;
		}
		command2Increment = 0;

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
		//detachInterrupt(TACH_PIN);
		//attachInterrupt(TACH_PIN, tachCalibrationISR, tachTriggerType);
		tachCalibrateRunning = true;
		for(int i=0;i<pulsesPerRev;i++){
			tachCalibrationData[i] = 1;
		}
		tachCalibrated = true;


		break;
	case MODE_TARE:
		commandTime = 0;
		commandMicros = 250 * 1000;
		tare();
		commandTrigger.begin(commandISR, commandUpdateRateMicros);

		//commandIndex++;
		//runCurrentCommand();
		break;
	}
}

void testISR(){
	//commandTrigger.end();

	dshotOut(48);

	//commandTrigger.begin(testISR, 1000); // start logger


}

void idleISR(){
	if (useDshot) {
		dshotThrottle(0);
	}

}

void commandISR(){
	if( commandTime > commandMicros ){
		// this command has run over its end time, make sure the final value is set and then advance
		commandIndex++;
		runCurrentCommand();
		//return;
	}
	motorValue += commandIncrement;
	auxValue += command2Increment;
	AUX.writeMicroseconds(auxValue);
	if (useDshot) {
		dshotThrottle(motorValue);
		if (( motorValue == readDshot() )&( commandIdleTime <= idleUpdateRateMicros )) {
			return;
		}

	} else {
		ESC.writeCommand( motorValue );
	}
	commandIdleTime = 0;

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

		adc->adc0->startSingleRead(LOADSENSE_PIN);
		loadSamplerActive = true;


	} else if(loadSamplerActive){
		scaleUpdated = true;
		loadSamplerActive = false;
		scaleValue=(uint16_t)adc->adc0->readSingle();


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
		if( (tempShutdownValue>0)&&( tempValues[tempIndex.write]<tempShutdownValue) ){
			//shutdown test
			abortTest=true;
			abortReason = ABORT_DANGER;
			Serial.println("temp abort");
		}
		tempIndex.nextWrite();
	}
}

void tachISR() {
	unsigned long time;
	time = tachTime;
	if (time < tachDebounce) {
		bounceCount++;
		return;
	}
	if (tachCalibrated){
		tachCalibrationIndex.nextRead();
		lastTachPulse = time;// /tachCalibrationData[tachCalibrationIndex.read]; // compensate for partial rotation
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
		float totalPulse = 0;
		for(int i=0;i<pulsesPerRev;i++){
			totalPulse = totalPulse + tachCalibrationTemp[i];
			//Serial.println(tachCalibrationTemp[i]);

		}

		if (tachCalibrated){ //update calibration data with running average
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

void setSamplerADCSettings(){
	//adc->setReference(ADC_REFERENCE::REF_3V3 , ADC_0);
	adc->setReference(ADC_REFERENCE::REF_EXT, ADC_0);
    adc->setAveraging(ADCAveraging, ADC_0); // set number of averages
    adc->setResolution(16, ADC_0); // set bits of resolution
    adc->setConversionSpeed(ADC_CONVERSION_SPEED::HIGH_SPEED_16BITS, ADC_0); // change the conversion speed
    adc->setSamplingSpeed(ADC_SAMPLING_SPEED::HIGH_SPEED   , ADC_0); // change the sampling speed

	//adc->setReference(ADC_REFERENCE::REF_3V3 , ADC_1);
	adc->setReference(ADC_REFERENCE::REF_EXT, ADC_1);
    adc->setAveraging(ADCAveraging, ADC_1); // set number of averages
    adc->setResolution(16, ADC_1); // set bits of resolution
    adc->setConversionSpeed(ADC_CONVERSION_SPEED::HIGH_SPEED_16BITS, ADC_1); // change the conversion speed
    adc->setSamplingSpeed(ADC_SAMPLING_SPEED::HIGH_SPEED   , ADC_1); // change the sampling speed

    adcMaxValue = adc->getMaxValue(ADC_0);

    //adc->enableCompare(adcMaxValue, 0, ADC_0);
    //adc->enableCompare(adcMaxValue, 0, ADC_1);
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
	sampleBuffer[index].calibrate = false;
	sampleBuffer[index].tachIndex = 0;
}

void zeroSampleBuffers(){
	//zero out all of the sample buffers
	for (unsigned int i=0; i<MAXSAMPLES; i++ ) {
		zeroSample(i);
	}
}

void resetCommandBuffer(){
	//reset the entire command buffer
	for (unsigned int i=0; i<COMMANDBUFFER_SIZE; i++ ) {
		commandBuffer[i].mode = MODE_END;
		commandBuffer[i].time = 0;
		commandBuffer[i].value = 0;
		commandBuffer[i].value2 = -1;
		commandBuffer[i].useMicros = false;
	}
}

void vbatAutorange(){
	digitalWrite(RANGE_3S, 0);
	digitalWrite(RANGE_4S, 0);
	digitalWrite(RANGE_5S, 0);
	digitalWrite(CALIBRATION_SENSE, 0);
	digitalWrite(BATTERY_SENSE, 1);
	setSamplerADCSettings();

	delay(1); // let the vsense settle
	uint16_t raw;

	raw = (uint16_t)adc->analogRead( VSENSE_PIN, ADC_1);
	if (raw*correctionFactor < 1.2) {
		digitalWrite(RANGE_3S, 1);
		vCalibrate.active = vCalibrate.cell3;
		vCalibrate.activeOffset = vCalibrate.cell3Offset;
		Serial5.println("set 3s");
	} else {
		vCalibrate.active = vCalibrate.cell6;
		vCalibrate.activeOffset = vCalibrate.cell6Offset;
		Serial5.println("set 6s");
	}
	delay(1); // let the vsense settle

}

void checkTempSenors(){
	//adc->adc0->disableCompare();
	//adc->adc1->disableCompare();
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

    adcMaxValue = adc->getMaxValue(ADC_0);

    adc->enableCompare(adcMaxValue, 0, ADC_0);
    adc->enableCompare(adcMaxValue, 0, ADC_1);
	//adc->adc0->wait_for_cal();

    delay(1);
    //while (!adc->isComplete(ADC_0)){};
    //while (!adc->isComplete(ADC_1)){};

    correctionFactor = 3.3/adcMaxValue;

    for (unsigned int i=0; i<4; i++ ) {
		rawTemp = (uint16_t)adc->analogRead(tempPins[i]);
		Serial.print(rawTemp*correctionFactor);
		Serial.print(" ");
		if( (rawTemp*correctionFactor) > 3.0 ){
			tempEnable[i]=false;
			Serial.print("disabling ");
			Serial.print(tempPins[i]);
			Serial.print(" ");
			Serial.println(i);
		} else {
			tempEnable[i]=true;
			Serial.print("enabling ");
			Serial.print(tempPins[i]);
			Serial.print(" ");
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


	if (useDshot) {
		if (getDshotUpdated()){
			resetDshotUpdated();
			//make note of the current command micros for the ESC
			sampleBuffer[sampleBufferIndex.write].commandValuePresent = true;
			sampleBuffer[sampleBufferIndex.write].commandValue = readDshot();
		}
	} else {
		sampleBuffer[sampleBufferIndex.write].commandValuePresent = true;
		sampleBuffer[sampleBufferIndex.write].commandValue = ESC.readCommand();
	}

	//RPM
	if(tachUpdate){
		tachUpdate = false;
		sampleBuffer[sampleBufferIndex.write].tachPulsePresent = true;
		sampleBuffer[sampleBufferIndex.write].tachPulse = lastTachPulse;
		sampleBuffer[sampleBufferIndex.write].tachIndex = tachCalibrationIndex.read+1;

		if(tachCalibrateRunning){
			sampleBuffer[sampleBufferIndex.write].calibrate = true;
		}

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

void statFunc() {
	uint16_t raw = 0;
	float value;

	Serial5.println("status");

	adc->setReference(ADC_REFERENCE::REF_3V3 , ADC_0);
    adcMaxValue = adc->getMaxValue(ADC_0);

	raw = (uint16_t)adc->analogRead(TACH_PIN_A);
    Serial5.print("Tach sense:");
    Serial5.println( (float)raw/adcMaxValue );

	setSamplerADCSettings();
	digitalWrite(CALIBRATION_SENSE, 0);
	digitalWrite(BATTERY_SENSE, 1);
	vbatAutorange();

    ADCresult = adc->analogSynchronizedRead(ISENSE_PIN, VSENSE_PIN);
    //     adc->startSynchronizedSingleRead(ISENSE_PIN, VSENSE_PIN);
    value = getVolts( (uint16_t)ADCresult.result_adc1 );
    Serial5.print("volt:");
    Serial5.print(value);
    Serial5.print(" ");
    Serial5.println( (uint16_t)ADCresult.result_adc1 );
    value = getAmps( (uint16_t)ADCresult.result_adc0 );
    Serial5.print("amp:");
    Serial5.print(value);
    Serial5.print(" ");
    Serial5.println( (uint16_t)ADCresult.result_adc0 );

	scaleValue=adc->analogRead(LOADSENSE_PIN);

	//scaleValue = scale.get_units();
    Serial5.print("thrust:");
    Serial5.print((scaleValue-tareValue)/scaleCalibrationValue,4);
    Serial5.print(" ");
    Serial5.println(scaleValue-tareValue);

}

void tachCalibrateLow() {
	tachCalibrateLog("TLC");
}
void tachCalibrateHigh() {
	tachCalibrateLog("THC");
}
void tachCalibrateDelta() {
	const int line_buffer_size = 16;
	char buffer[line_buffer_size];

	uint16_t lowValue = 0;
	uint16_t highValue = 0;
	uint16_t thisDelta = 0;
	uint16_t bigDelta = 0;
	uint16_t highIndex = 0;

	ifstream tlc("TLC");
	ifstream thc("THC");

	for (uint16_t i=0; i<800; i++){
		tlc.getline(buffer, line_buffer_size, '\n');
		lowValue = atof(buffer);
		thc.getline(buffer, line_buffer_size, '\n');
		highValue = atof(buffer);
		thisDelta = lowValue-highValue;

		Serial.print(i);
		Serial.print(" ");
		Serial.println(thisDelta);

		if (thisDelta>bigDelta) {
			bigDelta = thisDelta;
			highIndex = i;
			Serial5.print("peak");
			Serial5.print(" ");
			Serial5.print(i);
			Serial5.print(" ");
			Serial5.println(bigDelta);
		}
	}

	tlc.close();
	thc.close();

	Serial5.print("tach calibrate value: ");
	Serial5.print(highIndex);
	Serial5.print(" ");
	Serial5.println(bigDelta);


}

void tachCalibrateLog(const char logfile[]) {
	char str[80];
    uint16_t raw;
	if (!sd.begin()) sd.initErrorHalt("SdFatSdioEX begin failed");
	sd.chvol();

    Serial.println("cal start");
	adc->setReference(ADC_REFERENCE::REF_3V3 , ADC_0);
	//adc->enableCompare(1.0/3.3*adc->getMaxValue(ADC_0), 0, ADC_0);
    //while (!adc->isComplete(ADC_0)){};
    adcMaxValue = adc->getMaxValue(ADC_0);
    Serial.println("cal mid");

	if (!file.open(logfile, O_WRITE | O_CREAT)) {
		Serial.print("open failed");
		return;
	}

	for (int i=0; i<800; i++){
		setWiper(i+100);
	    raw = (uint16_t)adc->analogRead(TACH_PIN_A);

		sprintf(str, "%i\n", raw );
		file.write(str);
	}
	file.flush();
	file.close();
	Serial5.print("calibrate log saved ");
	Serial5.println(logfile);

}

void testFunc() {
    uint16_t raw;
	checkTempSenors();
	checkTempSenors();
	setSamplerADCSettings();
	checkTempSenors();
	checkTempSenors();
    return;

	while(true){
		adc->setReference(ADC_REFERENCE::REF_3V3 , ADC_0);
	    adcMaxValue = adc->getMaxValue(ADC_0);
	    raw = (uint16_t)adc->analogRead(TACH_PIN_A);
		Serial.println(raw*correctionFactor);
		delay(1000);
	}

	return;

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

    //uint16_t raw;
    raw = (uint16_t)adc->analogRead(TACH_PIN_A);
	Serial.println(raw*correctionFactor);

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

	bounceCount = 0;

	digitalWrite(LED_PIN, 0);

	loadConfig();
	//loadProgram();
	zeroSampleBuffers();
	sampleBufferIndex.reset();
	overrunS = 0;
	maxSampleBuffer = 0;

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
	vbatAutorange();

	logHead();

	// start the log sampling ISR
	attachInterrupt(TACH_PIN, tachISR, tachTriggerType);
	tachTime = 0;
	lastTachPulse = 1000000/( (1.0/60) *pulsesPerRev); //start tach at 1 rpm

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

			ringIndexManager byteIndex(33);
			byteIndex.reset();
			// advance by 2 to leave room for bitmask
			byteIndex.nextWrite();
			byteIndex.nextWrite();

			byteMap convert;
			uint8_t allSample[29];
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

				if (sampleBuffer[sampleBufferIndex.read].tachIndex > 0){
					sampleMask |= SAMPLE_TACH_INDEX;
					allSample[byteIndex.write]=sampleBuffer[sampleBufferIndex.read].tachIndex;
					byteIndex.nextWrite();

				}

				if(sampleBuffer[sampleBufferIndex.read].calibrate){ // if the tach calibration was running reset the ISR
					sampleMask |= SAMPLE_CALIBRATE;
				}


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
				convert.slong = sampleBuffer[sampleBufferIndex.read].thrust;
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
			if (useDshot){
				idler.begin(idleISR, idleUpdateRateMicros);
			} else {
				ESC.writeCommand(0);
			}
			commandTrigger.end();

			//reset the command program to the beginning
			commandIndex=0;
			// kill the log sampling ISR
			logSampler.end();
			// kill the tach ISR
			detachInterrupt(TACH_PIN);
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
			Serial.print("bounce count ");
			Serial.println(bounceCount);

			float calibTotal = 0;
			for(int i=0;i<10;i++){
				calibTotal = calibTotal+tachCalibrationData[i];
				Serial.print(" ");
				Serial.print(tachCalibrationData[i],6);
			}
			Serial.print(" ");
			Serial.print(calibTotal,6);
			Serial.println();


			if (overrunS > 0) {
				Serial.print("overS ");
				Serial.println(overrunS);
			}
			file.flush();
			file.close();
			running = false;

		}

	}

    adc->disableInterrupts();

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

	file.write("log version: 3\n");
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
	sprintf(str, "vCalibrate: %.6f\n", vCalibrate.active );
	file.write(str);
	sprintf(str, "vOffset: %.6f\n", vCalibrate.activeOffset );
	file.write(str);
	sprintf(str, "aCalibrate: %.6f\n", vCalibrate.amp );
	file.write(str);
	sprintf(str, "aOffset: %.6f\n", vCalibrate.ampOffset );
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
	sprintf(str, "loaded program: %s\n", loadedProgram );
	file.write(str);
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

	// temp = 1/( ( 1/nominalTemp ) + LOG(resistance/nominalResist)/B )
	// temp = 1/( ( 1/298.15 ) + LOG(resistance/10000)/B )
	//convert K to C
	// C = K - 273.15

	//get absolute voltage
	float rawVolt = rawValue*correctionFactor;

	float r = rawVolt/0.0001;  // resistance from fixed current driver

	float kValue = 1/( ( 1/298.15 ) + log(r/10000)/thermBValue );
	float cValue = kValue - 273.15;
	return cValue;
}


uint16_t getRawFromTemp(const float cValue){
	float kValue = cValue + 273.15;
	float r = exp(((1/kValue) - (1/298.15))*thermBValue)*10000;
	float rawVolt = r*0.0001;

	uint16_t rawValue = rawVolt/(vRef/pow(2,16));
	return rawValue;
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
	//float rawVolt = rawValue*correctionFactor;

	//AttoPilot 90A sensor

	float vValue = (rawValue+vCalibrate.activeOffset)/vCalibrate.active; ;
	//allegro 100a divider values
	// 25.44/1.278   total 26.72
	//double vValue = rawVolt / (1.278/26.72 ) ;

	//vValue = vValue * 1.327;
	return vValue;
}

float getAmps(const float rawValue){
	// convert raw ADC reading into battery voltage


	//get absolute voltage
	//float rawVolt = rawValue*correctionFactor;

	//AttoPilot 90A sensor
	float aValue = (rawValue+vCalibrate.ampOffset)/vCalibrate.amp;

	//allegro 100a divider values
	// 20mv/A ,  0amp point 1/2 supply voltage
	//2.175 / 6.71  total 8.89
	//double sensorValue = rawVolt / (6.71/8.89) ;
	//double offset = (3.76 / 2.0);
	//double aValue = (sensorValue-offset) * (1.0/0.02 ) ;

	//aValue = ( aValue - 33.5 )*3.3
	return aValue;
}

void tare() {
	//scale.tare(8);				        // reset the scale to 0, 8 samples average
	tareValue =	adc->analogRead(LOADSENSE_PIN);

}

void setCommandUpdateRate(uint16_t rate){
	commandUpdateRate = rate; // ESC update in hz
	commandUpdateRateMicros = (1.0/commandUpdateRate)*1000000;
}

void setAuxCommandRate(uint16_t rate){
	auxCommandRate = rate; // ESC update in hz
	auxCommandRateMicros = (1.0/auxCommandRate)*1000000;
	AUX.attach(AUXSERVO_PIN);
	AUX.writeMicroseconds(1001);
}

void setAuxMinUsec(uint16_t usec){
	auxMinUsec = usec;
}

void setAuxMaxUsec(uint16_t usec){
	auxMaxUsec = usec;
}

void setSampleRate(uint16_t rate){
	sampleRate = rate; // log sampler rate in hz
	sampleRateMicros = (1.0/sampleRate)*1000000;
}

void loadConfig() {
	loadConfigFile("calibrate.cfg");
	loadConfigFile("config.cfg");
}

void loadConfigFile(const char configFile[]) {
	if (!sd.begin()) sd.initErrorHalt("SdFatSdioEX begin failed");
	sd.chvol();

	  const int line_buffer_size = 256;
	  char buffer[line_buffer_size];

	  char * propertyValue;
	  float value;

	  ifstream sdin(configFile);
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
		  if (strncmp (buffer,"auxCommandRate",strlen("auxCommandRate")) == 0)
		    {
			  if (propertyValue==NULL) continue;
			  value = atof(propertyValue);
		      Serial.println("setting auxCommandRate");
		      setAuxCommandRate( (uint16_t)value );
		      continue;
		    }
		  if (strncmp (buffer,"auxMinUsec",strlen("auxMinUsec")) == 0)
		    {
			  if (propertyValue==NULL) continue;
			  value = atof(propertyValue);
		      Serial.println("setting auxMinUsec");
		      setAuxMinUsec( (uint16_t)value );
		      continue;
		    }
		  if (strncmp (buffer,"auxMaxUsec",strlen("auxMaxUsec")) == 0)
		    {
			  if (propertyValue==NULL) continue;
			  value = atof(propertyValue);
		      Serial.println("setting auxMaxUsec");
		      setAuxMaxUsec( (uint16_t)value );
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
			  if (strncmp (propertyValue," FALLING",strlen(" FALLING")) == 0)
			  {
				  value = FALLING;
			  } else if (strncmp (propertyValue," CHANGE",strlen(" CHANGE")) == 0)
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
		  if (strncmp (buffer,"tempShutDown",strlen("tempShutDown")) == 0)
		    {
			  if (propertyValue==NULL) continue;
			  value = atof(propertyValue);
			  tempShutdownValue = getRawFromTemp( value );
		      Serial.print("setting tempShutdownValue ");
		      Serial.print(value);
		      Serial.print(" ");
		      Serial.println(tempShutdownValue);
		      continue;
		    }
		  if (strncmp (buffer,"loadCellCalibration",strlen("loadCellCalibration")) == 0)
		    {
			  if (propertyValue==NULL) continue;
			  value = atof(propertyValue);
		      Serial.println("setting loadCellCalibration");
		      scaleCalibrationValue = value;
		      continue;
		    }
		  if (strncmp (buffer,"ADCAveraging",strlen("ADCAveraging")) == 0)
		    {
			  if (propertyValue==NULL) continue;
			  value = atof(propertyValue);
		      Serial.println("setting ADCAveraging");
		      ADCAveraging = (uint8_t)value;
		      continue;
		    }
		  if (strncmp (buffer,"tachSensitivity",strlen("tachSensitivity")) == 0)
		    {
			  if (propertyValue==NULL) continue;
			  value = atof(propertyValue);
		      Serial.println("setting tachSensitivity");
		      setWiper(value);
		      continue;
		    }
		  if (strncmp (buffer,"vCalibrate3S",strlen("vCalibrate3S")) == 0)
		    {
			  if (propertyValue==NULL) continue;
			  value = atof(propertyValue);
		      Serial.println("setting vCalibrate3S");
		      vCalibrate.cell3 = value;
		      continue;
		    }
		  if (strncmp (buffer,"vCalibrate4S",strlen("vCalibrate4S")) == 0)
		    {
			  if (propertyValue==NULL) continue;
			  value = atof(propertyValue);
		      Serial.println("setting vCalibrate4S");
		      vCalibrate.cell4 = value;
		      continue;
		    }
		  if (strncmp (buffer,"vCalibrate5S",strlen("vCalibrate5S")) == 0)
		    {
			  if (propertyValue==NULL) continue;
			  value = atof(propertyValue);
		      Serial.println("setting vCalibrate5S");
		      vCalibrate.cell5 = value;
		      continue;
		    }
		  if (strncmp (buffer,"vCalibrate6S",strlen("vCalibrate6S")) == 0)
		    {
			  if (propertyValue==NULL) continue;
			  value = atof(propertyValue);
		      Serial.println("setting vCalibrate6S");
		      vCalibrate.cell6 = value;
		      continue;
		    }
		  if (strncmp (buffer,"vOffset3S",strlen("vOffset3S")) == 0)
		    {
			  if (propertyValue==NULL) continue;
			  value = atof(propertyValue);
		      Serial.println("setting vOffset3S");
		      vCalibrate.cell3Offset = value;
		      continue;
		    }
		  if (strncmp (buffer,"vOffset4S",strlen("vOffset4S")) == 0)
		    {
			  if (propertyValue==NULL) continue;
			  value = atof(propertyValue);
		      Serial.println("setting vOffset4S");
		      vCalibrate.cell4Offset = value;
		      continue;
		    }
		  if (strncmp (buffer,"vOffset5S",strlen("vOffset5S")) == 0)
		    {
			  if (propertyValue==NULL) continue;
			  value = atof(propertyValue);
		      Serial.println("setting vOffset5S");
		      vCalibrate.cell5Offset = value;
		      continue;
		    }
		  if (strncmp (buffer,"vOffset6S",strlen("vOffset6S")) == 0)
		    {
			  if (propertyValue==NULL) continue;
			  value = atof(propertyValue);
		      Serial.println("setting vOffset6S");
		      vCalibrate.cell6Offset = value;
		      continue;
		    }
		  if (strncmp (buffer,"aCalibrate",strlen("aCalibrate")) == 0)
		    {
			  if (propertyValue==NULL) continue;
			  value = atof(propertyValue);
		      Serial.println("setting aCalibrate");
		      vCalibrate.amp = value;
		      continue;
		    }
		  if (strncmp (buffer,"aOffset",strlen("aOffset")) == 0)
		    {
			  if (propertyValue==NULL) continue;
			  value = atof(propertyValue);
		      Serial.println("setting aOffset");
		      vCalibrate.ampOffset = value;
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
		char * midTokenPtr;

		unsigned long cTime = 0;
		float cValue = 0;
		float cValue2 = -1;
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

			  //store next value pointer
			  midTokenPtr = strtok( NULL, " ");
			  if (tokenPtr==NULL) continue;

			  //check for 3rd value.
			  tokenPtr = strtok( NULL, " ");
			  if (tokenPtr==NULL) {
				  //If it doesn't exist pass the previous token value along for time parsing
				  tokenPtr = midTokenPtr;
				  cValue2 = -1;

			  } else {
				  //If it exists assume dual servo output command
				  cValue2 = atof(midTokenPtr);
			  }

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
				commandBuffer[bufferIndex].value = 2000*(cValue/100);
				if (cValue2 > -1){
					commandBuffer[bufferIndex].value2 = 2000*(cValue2/100);
				} else {
					commandBuffer[bufferIndex].value2 = -1;
				}
				Serial5.println( commandBuffer[bufferIndex].value);
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

			  //store next value pointer
			  midTokenPtr = strtok( NULL, " ");
			  if (tokenPtr==NULL) continue;

			  //check for 3rd value.
			  tokenPtr = strtok( NULL, " ");
			  if (tokenPtr==NULL) {
				  //If it doesn't exist pass the previous token value along for time parsing
				  tokenPtr = midTokenPtr;
				  cValue2 = -1;

			  } else {
				  //If it exists assume dual servo output command
				  cValue2 = atof(midTokenPtr);
			  }

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
				commandBuffer[bufferIndex].value = 2000*(cValue/100);
				if (cValue2 > -1){
					commandBuffer[bufferIndex].value2 = 2000*(cValue2/100);
				} else {
					commandBuffer[bufferIndex].value2 = -1;
				}
				Serial5.println( commandBuffer[bufferIndex].value);
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
				commandBuffer[bufferIndex].value = 2000*(cValue/100);
				Serial5.println( commandBuffer[bufferIndex].value);
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


void runSerialCommand(){

	if (strncmp (serialCommand,"test",strlen("test")) == 0) {
		Serial.println("got test");
		testFunc();
	} else if (strncmp (serialCommand,"stat",strlen("stat")) == 0) {
		Serial.println("got stat");
		statFunc();
	} else if (strncmp (serialCommand,"tare",strlen("tare")) == 0) {
		Serial.println("got tare");
		tare();
	} else if (strncmp (serialCommand,"tlc",strlen("tlc")) == 0) {
		Serial.println("got tlc");
		tachCalibrateLow();
	} else if (strncmp (serialCommand,"thc",strlen("thc")) == 0) {
		Serial.println("got thc");
		tachCalibrateHigh();
	} else if (strncmp (serialCommand,"tcc",strlen("tcc")) == 0) {
		Serial.println("got tcc");
		tachCalibrateDelta();
	} else if (strncmp (serialCommand,"run",strlen("run")) == 0) {

		Serial.println("got run");
		char* fileString = serialCommand + strlen("run");
		loadedProgram = fileString;
		if(strlen(fileString)){
			loadProgram(fileString);
		} else {
			loadProgram((char *)"program.txt");
		}

		doTestLog();
	} else if (strncmp (serialCommand,"list",strlen("list")) == 0) {
		Serial.println("got list");
		SdFile file;
		char name[100];

		if (!sd.begin()) sd.initErrorHalt("SdFatSdioEX begin failed");
		sd.chvol();
		sd.vwd()->rewind();
		Serial5.println("<BeginDirList>");

		while (file.openNext(sd.vwd(), O_READ)) {
			file.getName(name,100);
			if (endsWith(name, ".txt")) {
				if (!((strncmp(name,"config",strlen("config")) == 0)|
					  (strncmp(name,"log",strlen("log")) == 0))  ) {

					Serial5.print("<");
					Serial5.print(name);
					Serial5.println(">");
				}
			}
			file.close();

		}  // end of listing files
		Serial5.println("<EndDirList>");


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

uint16_t commandToPWM( uint16_t commandValue){
	return ( (commandValue/2)+1000 );
}
