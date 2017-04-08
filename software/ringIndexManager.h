#include <stdint.h>

class ringIndexManager {
public:
	ringIndexManager(uint16_t);
	void nextRead();
	void nextWrite();
	uint16_t peekRead();
	uint16_t peekWrite();
	bool isFull();
	void reset();
	uint16_t getFillLength();


	volatile uint16_t read = 0;
	volatile uint16_t write = 0;
private:
	uint16_t mySize = 0;
	volatile uint16_t fillCount = 0;

};
