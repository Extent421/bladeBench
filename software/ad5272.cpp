#include "ad5272.h"

void enableWiper(){
	  //enable wiper change
	Wire2.beginTransmission(DPADDRESS);
	Wire2.write(0x1C);
	Wire2.write(0x02);
	Wire2.endTransmission();     // stop transmitting
}

int readControl(){
	Wire2.beginTransmission(DPADDRESS);
	Wire2.write(0x20);
	Wire2.write(0x00);

	Wire2.endTransmission();     // stop transmitting
	return(receiveI2C());
}

int readWiper(){
	Wire2.beginTransmission(DPADDRESS);
	Wire2.write(0x8);
	Wire2.write(0x0);

	Wire2.endTransmission();     // stop transmitting
	return(receiveI2C());
}

void setWiper(uint16_t value){
	if (value > 1024) value = 1024;
	Wire2.beginTransmission(DPADDRESS);
	Wire2.write( (uint8_t)(value>>8)|4 );
	Wire2.write( (uint8_t)(value & 0xff) );
	Wire2.endTransmission();     // stop transmitting
}



/*
this function receives 2 Bytes from the I2C interface and returns the result
*/
int receiveI2C() {
	Wire2.beginTransmission(DPADDRESS);
	Wire2.requestFrom(DPADDRESS, 2);
   int cInt = 0;
   int counter = 0;
   while(Wire2.available())    // slave may send less than requested
    {
     int c = Wire2.read();    // receive a byte as character
     counter = counter + 1;
     if(counter == 1) {
       cInt = c*256;
     }
     if(counter != 1) {
       cInt = cInt+c;
     }
    }
   Wire2.endTransmission();
   return cInt;
}
