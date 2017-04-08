#include "dshot.h"


DMAChannel dma1;
DMAChannel dma2;
DMAChannel dma3;

static uint8_t dshotMask = ESC_PIN_MASK;
uint8_t dshotCommandBuffer[16];
uint16_t lastDshotMotorValue = 48;

bool dshotUpdated = false;

void setupDshotDMA(void){
	//for  (__MK64FX512__) || defined(__MK66FX1M0__)
	FTM2_SC = 0; //status and control
	FTM2_CNT = 0; // reset counter
	uint32_t mod = (F_BUS + DSHOT_CLOCK / 2) / DSHOT_CLOCK;
	FTM2_MOD = mod - 1; // set trigger length
	FTM2_SC = FTM_SC_CLKS(1) | FTM_SC_PS(0);  //set clock source 1 and prescale 0
	FTM2_C0SC = 0x69;
	FTM2_C1SC = 0x69;
	FTM2_C0V = (mod * DSHOT_0_TIMING) >> 8;
	FTM2_C1V = (mod * DSHOT_1_TIMING) >> 8;
	// FTM2_CH0, PTA10 (not connected), triggers DMA(port A) on rising edge
	PORTA_PCR10 = PORT_PCR_IRQC(1)|PORT_PCR_MUX(3);

	// DMA channel #1 sets WS2811 high at the beginning of each cycle
	dma1.source(dshotMask);
	dma1.destination(GPIOC_PSOR); //set pin
	dma1.transferSize(1);
	dma1.transferCount(16);
	dma1.disableOnCompletion();

	// DMA channel #2 writes the pixel data at 23% of the cycle
	dma2.sourceBuffer((uint8_t *)dshotCommandBuffer, 16);
	dma2.destination(GPIOC_PCOR); //clear pin for zero
	dma2.transferSize(1);
	dma2.transferCount(16);
	dma2.disableOnCompletion();

	// DMA channel #3 clear all the pins low at 69% of the cycle
	dma3.source(dshotMask);
	dma3.destination(GPIOC_PCOR); //clear pin
	dma3.transferSize(1);
	dma3.transferCount(16);
	dma3.disableOnCompletion();

	//for  (__MK64FX512__) || defined(__MK66FX1M0__)
	// route the edge detect interrupts to trigger the 3 channels
	dma1.triggerAtHardwareEvent(DMAMUX_SOURCE_PORTA);
	dma2.triggerAtHardwareEvent(DMAMUX_SOURCE_FTM2_CH0);
	dma3.triggerAtHardwareEvent(DMAMUX_SOURCE_FTM2_CH1);
	DMAPriorityOrder(dma3, dma2, dma1);

}


void writeDshot(void){
	//for  (__MK64FX512__) || defined(__MK66FX1M0__)
	FTM2_C0SC = 0x28;
	FTM2_C1SC = 0x28;
	//delay(1);
	uint32_t cv = FTM2_C1V; //channel 1 count value

	noInterrupts();
	// CAUTION: this code is timing critical.
	while (FTM2_CNT <= cv) ;
	while (FTM2_CNT > cv) ; // wait for beginning of a cycle
	while (FTM2_CNT < cv) ;
	FTM2_SC = 0;             // stop FTM2 timer (hopefully before it rolls over)
	PORTA_ISFR = (1<<10);    // clear any prior rising edge
	uint32_t tmp __attribute__((unused));

	FTM2_C0SC = 0x28; // FTM_CSC_PWM_EDGE_HI
	tmp = FTM2_C0SC;         // clear any prior timer DMA triggers
	FTM2_C0SC = 0x69; // FTM_CSC_DMA | FTM_CSC_PWMEDGE_HI | FTM_CSC_IRQ

	FTM2_C1SC = 0x28;
	tmp = FTM2_C1SC;
	FTM2_C1SC = 0x69;

	// enable all 3 DMA channels
	dma1.enable();
	dma2.enable();
	dma3.enable();

	FTM2_SC = FTM_SC_CLKS(1) | FTM_SC_PS(0); // restart FTM2 timer
	interrupts();

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
	memset(dshotCommandBuffer, 0, 16);
	for(int i; i<16; i++){ // scan all the bits in the packet
		if( !(bool)((1<<i)&value) ){ // if the bit is 0 write a reset byte to the buffer
			dshotCommandBuffer[15-i] = ESC_PIN_MASK; // pack buffer MSB first
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

	if (value < 48){
		value = 48;
	} else if (value > 2047){
		value = 2047;
	}

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
