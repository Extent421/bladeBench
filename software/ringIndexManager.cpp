#include "ringIndexManager.h"

ringIndexManager::ringIndexManager(uint16_t size) {
	mySize = size;
}

void ringIndexManager::nextRead() {
	read = (read+1) % mySize;
	fillCount--;
}

void ringIndexManager::nextWrite() {
	write = (write+1) % mySize;
	fillCount++;
}

uint16_t ringIndexManager::peekRead() {
	return( (read+1) % mySize );
}

uint16_t ringIndexManager::peekWrite() {
	return( (write+1) % mySize );
}

void ringIndexManager::reset() {
	read = 0;
	write = 0;
	fillCount = 0;
}

bool ringIndexManager::isFull() {
	if (fillCount >= mySize-1) { return(true); }
	else { return(false); }
}

uint16_t ringIndexManager::getFillLength() {
	return( fillCount );
}
