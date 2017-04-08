#ifndef ad5272_h
#define ad5272_h

#include "pins.h"
#include <i2c_t3.h>

int receiveI2C();

void enableWiper();
int readControl();
int readWiper();
void setWiper(uint16_t value);

#endif /* ad5272_h */
