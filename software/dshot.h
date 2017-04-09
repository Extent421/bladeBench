#ifndef dshot_h
#define dshot_h

#include <Arduino.h>
#include "DMAChannel.h"

#include "pins.h"

#define DSHOT_COMMAND_LENGTH 16
#define DSHOT_BUFFER_LENGTH DSHOT_COMMAND_LENGTH+1

#define FTM_PINCFG(pin) FTM_PINCFG2(pin)
#define FTM_PINCFG2(pin) CORE_PIN ## pin ## _CONFIG
#define FTM0_CH2_PIN  9

#define FTM_SC_PRESCALE1 0x00
#define FTM_SC_PRESCALE2 0x01
#define FTM_SC_PRESCALE4 0x02
#define FTM_SC_PRESCALE8 0x03
#define FTM_SC_PRESCALE16 0x04
#define FTM_SC_PRESCALE32 0x05
#define FTM_SC_PRESCALE64 0x06
#define FTM_SC_PRESCALE128 0x07

#define FTM_SC_CLK_NONE 0x00
#define FTM_SC_CLK_SYS 0x08
#define FTM_SC_CLK_FIXED 0x10
#define FTM_SC_CLK_EXT 0x18

#define FTM_SC_COUNT_UP 0x00
#define FTM_SC_COUNT_UPDOWN 0x20

#define FTM_SC_IRQ 0x40

#define FTM_SC_OVERFLOW_FLAG 0x80

#define FTM_CSC_DMA 0x01

#define FTM_CSC_PWM_EDGE_HI 0x28
#define FTM_CSC_PWM_EDGE_LO 0x24


#define FTM_CSC_IRQ 0x40
#define FTM_CSC_OVERFLOW_FLAG 0x80



// clock in hz
#define DSHOT_CLOCK 600000
// bit timing as a % of clock rate
#define DSHOT_0_TIMING  (int)(0.38*255)
#define DSHOT_1_TIMING  (int)(0.75*255)


void setupDshotDMA(void);
void writeDshot(void);
uint8_t getDshotChecksum(uint16_t value);
void fillDshotBuffer(uint16_t value);
void dshotThrottle(uint16_t value);
void dshotOut(uint16_t value);
uint16_t readDshot(void);
bool getDshotUpdated(void);
void resetDshotUpdated(void);


#endif /* dshot_h */
