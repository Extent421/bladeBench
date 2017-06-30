#include "dshot.h"


DMAChannel dma;

uint8_t dshotCommandBuffer[DSHOT_BUFFER_LENGTH];
uint16_t lastDshotMotorValue = 48;

bool dshotUpdated = false;

void setupDshotDMA(void){
	//for  (__MK64FX512__) (__MK66FX1M0__)
	FTM0_SC = 0; // disable timer
	FTM0_CNT = 0; // reset counter
	uint32_t mod = (F_BUS + DSHOT_CLOCK / 2) / DSHOT_CLOCK;
	FTM0_MOD = mod - 1; // set trigger length
	FTM0_SC = FTM_SC_CLKS(1) | FTM_SC_PS(0);  //set clock source 1 and prescale 0
	FTM0_C1SC = FTM_CSC_DMA | FTM_CSC_PWM_EDGE_HI | FTM_CSC_IRQ;
	FTM0_C2SC = FTM_CSC_PWM_EDGE_HI;
	FTM0_C1V = (mod * 250) >> 8; // channel 1 drives the DMA transfer, trigger right at the end of each pulse
	FTM0_C2V = 0;

	dma.sourceBuffer((uint8_t *)dshotCommandBuffer, DSHOT_BUFFER_LENGTH);
	dma.destination(FTM0_C2V); //feed to channel 2 PWM length
	dma.transferSize(1);
	dma.transferCount(DSHOT_BUFFER_LENGTH);
	dma.disableOnCompletion();

	dma.triggerAtHardwareEvent(DMAMUX_SOURCE_FTM0_CH1);

	FTM_PINCFG(FTM0_CH2_PIN) = PORT_PCR_MUX(4) | PORT_PCR_DSE | PORT_PCR_SRE;
}


void writeDshot(void){
	dma.enable();
}

uint8_t getDshotChecksum(uint16_t value){
	uint8_t checksum = 0;
	for (uint8_t i = 0; i < 3; i++) {
		checksum ^=  value;
		value >>= 4;
	}
	checksum &= 0xf; // mask off the first nibble

	return checksum;

}

void fillDshotBuffer(uint16_t value){
	uint32_t mod = (F_BUS + DSHOT_CLOCK / 2) / DSHOT_CLOCK;
	memset(dshotCommandBuffer, 0, DSHOT_BUFFER_LENGTH);

	for(int i=0; i<DSHOT_COMMAND_LENGTH; i++){ // scan all the bits in the packet
		if( (bool)((1<<i)&value) ){
			dshotCommandBuffer[15-i] = (mod * DSHOT_1_TIMING) >> 8; // pack buffer MSB first
		} else {
			dshotCommandBuffer[15-i] = (mod * DSHOT_0_TIMING) >> 8; // pack buffer MSB first
		}
	}
}




void dshotThrottle(uint16_t value){
	lastDshotMotorValue = value;
	dshotUpdated = true;
	dshotOut(value+47);
}

void dshotOut(uint16_t value){
	uint16_t packet = 0;
	uint8_t checksum = 0;

	if (value < 47){
		value = 47;
	} else if (value > 2047){
		value = 2047;
	}

	//value = value-1;

	packet = value << 1;
	checksum = getDshotChecksum(packet);
	packet = (packet<<4)|checksum;
	fillDshotBuffer(packet);
	writeDshot();
}

uint16_t readDshot(void){
	return lastDshotMotorValue;
}

bool getDshotUpdated(void){
	return dshotUpdated;
}

void resetDshotUpdated(void){
	dshotUpdated = false;
}
