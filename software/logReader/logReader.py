import csv
import copy
import math
import pickle
import os
import gzip
import json

from bokeh.plotting import figure, output_file, show, reset_output, ColumnDataSource
from bokeh.models import HoverTool, Range1d, LinearAxis, LinearColorMapper, ColorBar, BasicTicker, PrintfTickFormatter, CustomJS, TapTool
from bokeh import events

import numpy.polynomial.polynomial as poly
import numpy

useCache = False

class smoother():
	medTaps = 6
	avgTaps = 6

	def __init__(self, medTaps=6, avgTaps=6):
		self.medAcc = []
		self.avgAcc = []
		self.medTaps = medTaps
		self.avgTaps = avgTaps

	def add(self, value):
			self.medAcc.append(value)
			self.medAcc = self.medAcc[-self.medTaps:]
			med = copy.deepcopy(self.medAcc)
			med.sort()

			self.avgAcc.append(  med[ int(len(med)/2 ) ]  )
			self.avgAcc = self.avgAcc[-self.avgTaps:]
	def get(self):
		sum=0
		for item in self.avgAcc:
			sum += item
		avg=sum/len(self.avgAcc)

		#if len(self.avgAcc) < self.avgTaps:
		#	print self.avgAcc

		return(avg)

MIN_SAMPLE_TIME = 100 #minimum time between sample readings in micros

SAMPLE_TIME	= 1<<0
SAMPLE_MOTORCOMMAND	= 1<<1
SAMPLE_TACH = 1<<2
SAMPLE_VOLT = 1<<3
SAMPLE_AMP = 1<<4
SAMPLE_THRUST = 1<<5
SAMPLE_T1 = 1<<6
SAMPLE_T2 = 1<<7
SAMPLE_T3 = 1<<8
SAMPLE_T4 = 1<<9
SAMPLE_TACH_INDEX = 1<<10
SAMPLE_CALIBRATE = 1<<11

TIMEROUNDING = 5

def readLog(file):
	print 'parsing log', file
	with open(file, 'rb') as csvfile:
		thisLine = ''
		while 'Time,' not in thisLine:
			lastRead = csvfile.tell()
			thisLine = csvfile.readline()
		csvfile.seek(lastRead)

		floatKeys = ['RPM', 'Volt', 'Amp', 'Thrust']
		intKeys = ['Motor Command', 'Time']
		csv = csv.DictReader(csvfile, delimiter=',', quotechar='|')

		allSamples = []
		index = {}
		try:
			for row in csv:
				thisSample = {}

				if not index.keys():
					for key in row.keys():
						index[key]=[]

				for key in row.keys():
					thisSample[key]=None

				for key in floatKeys:
					if row[key] != '':
						thisSample[key]=float(row[key])
						index[key].append(len(allSamples))
				for key in intKeys:
					if row[key] != '':
						thisSample[key]=int(row[key])
						index[key].append(len(allSamples))
				allSamples.append(thisSample)
		except:
			pass

	#interpolate
	for key in index:
		seq = index[key]
		for a, b in zip(seq, seq[1:]):
			length = b-a
			if length<2: continue
			start = allSamples[a][key]
			end = allSamples[b][key]
			delta = end-start
			for i in range(1,length):
				allSamples[a+i][key] =start + delta*(float(i)/length)


	return allSamples, index

def readBinaryLog(file):
	import struct
	print 'parsing log', file

	allKeys = ['RPM', 'RPMIndex', 'calibrate', 'Volt', 'Amp', 'Thrust','Motor Command', 'Time', 'T1', 'T2', 'T3', 'T4', 'autoCalibrate']
	allSamples = []
	index = {}
	for key in allKeys:
		index[key]=[]

	if useCache:
		if os.path.isfile(file+'.cache'):
			f = gzip.open(file+'.cache', 'rb')
			cached = pickle.load(f)
			f.close()
			return cached['allSamples'], cached['index']
 
	with open(file, 'rb') as f:
		adcMax = None
		vref = None
		dataStart = None
		vCalibrationFactor =  5.9652021980316 #3s mode
		loadCellCalib = 200.9647
		programName = None

		for line in iter(f.readline, ''):
			if 'adcMaxValue:' in line:
				adcMax = float(line.split(':')[-1])
			if 'vref:' in line:
				vref = float(line.split(':')[-1])
			if 'thermBValue:' in line:
				thermBValue = float(line.split(':')[-1])
			if 'pulse per rev:' in line:
				pulsePerRev = int(line.split(':')[-1])
			if 'loadcell calibration value:' in line:
				loadCellCalib = float(line.split(':')[-1])
			if 'vrange:' in line:
				if '6s' in line.split(':')[-1]:
					vCalibrationFactor =  13.0153255458302 #6s mode
				else:
					vCalibrationFactor =  5.9652021980316 #3s mode
			if 'loaded program:' in line:
				programName = line.split(':')[-1].strip()

			if line == 'Data Start:\n':
				dataStart = f.tell()
				break
		print 'found start', dataStart, adcMax, vref
		#f.seek(dataStart-1)

		correctionValue = vref/adcMax

		while True:
			thisSample = {}
			for key in allKeys:
				thisSample[key]=None

			data = f.read(2)
			if not len(data): break
			#unpacked = struct.unpack('<H', data)[0]
			#print 'unpacked', format(ord(data[0]), '02x'), format(ord(data[1]), '02x'), unpacked, bin(unpacked)[2:]

			flags = struct.unpack('<H', data)[0]

			if flags & SAMPLE_TIME:
				data = f.read(4)
				if not len(data): break
				unpacked = struct.unpack('<L', data)[0]
				thisSample['Time']=unpacked
				index['Time'].append(len(allSamples))

			if flags & SAMPLE_MOTORCOMMAND:
				data = f.read(2)
				if not len(data): break
				unpacked = struct.unpack('<h', data)[0]
				thisSample['Motor Command']=unpacked
				index['Motor Command'].append(len(allSamples))

			if flags & SAMPLE_TACH:
				data = f.read(4)
				if not len(data): break
				unpacked = struct.unpack('<L', data)[0]
				if unpacked == 0:
					rpm = -1
				else:
					rpm = (1000000.0/unpacked)*60
				thisSample['RPM']=rpm
				index['RPM'].append(len(allSamples))
			
			if flags & SAMPLE_TACH_INDEX:
				data = f.read(1)
				if not len(data): break
				unpacked = struct.unpack('<B', data)[0]
				thisSample['RPMIndex']=unpacked
				index['RPMIndex'].append(len(allSamples))

			if flags & SAMPLE_CALIBRATE:
				index['calibrate'].append(len(allSamples))

			if flags & SAMPLE_VOLT:
				data = f.read(2)
				if not len(data): break
				unpacked = struct.unpack('<H', data)[0]
				adcVolt = unpacked * correctionValue
				sensorVolt = adcVolt * vCalibrationFactor
				thisSample['Volt']=sensorVolt
				index['Volt'].append(len(allSamples))

			if flags & SAMPLE_AMP:
				data = f.read(2)
				if not len(data): break
				unpacked = struct.unpack('<H', data)[0]
				adcVolt = unpacked * correctionValue
				calibrationFactor = 34.5867331938442
				offset = 0.13
				sensorAmps = adcVolt * calibrationFactor + offset
				thisSample['Amp']=sensorAmps
				index['Amp'].append(len(allSamples))

			if flags & SAMPLE_THRUST:
				data = f.read(4)
				if not len(data): break
				temp = [data[0],data[1],data[2],data[3]]
				#unpacked = struct.unpack_from('<h', ''.join(temp))[0]
				unpacked = struct.unpack_from('<l', data)[0]
				
				#fix value overruns
				if unpacked > pow(2,22):
					unpacked = (unpacked - pow(2,23))
				elif unpacked < -pow(2,22):
					unpacked = (unpacked + pow(2,23))

				unpacked = unpacked/loadCellCalib
				#unpacked = unpacked*21.5
				thisSample['Thrust']=unpacked
				index['Thrust'].append(len(allSamples))

			if flags & SAMPLE_T1:
				data = f.read(2)
				if not len(data): break
				unpacked = struct.unpack('<H', data)[0]

				rawVolt = unpacked*correctionValue;
				r = rawVolt/0.0001;
				kValue = 1/( ( 1/298.15 ) + math.log(r/10000)/thermBValue );
				cValue = kValue - 273.15;

				thisSample['T1']=cValue
				index['T1'].append(len(allSamples))

			if flags & SAMPLE_T2:
				data = f.read(2)
				if not len(data): break
				unpacked = struct.unpack('<H', data)[0]

				rawVolt = unpacked*correctionValue;
				r = rawVolt/0.0001;
				kValue = 1/( ( 1/298.15 ) + math.log(r/10000)/thermBValue );
				cValue = kValue - 273.15;

				thisSample['T2']=cValue
				index['T2'].append(len(allSamples))

			if flags & SAMPLE_T3:
				data = f.read(2)
				if not len(data): break
				unpacked = struct.unpack('<H', data)[0]

				rawVolt = unpacked*correctionValue;
				r = rawVolt/0.0001;
				kValue = 1/( ( 1/298.15 ) + math.log(r/10000)/thermBValue );
				cValue = kValue - 273.15;

				thisSample['T3']=cValue
				index['T3'].append(len(allSamples))

			if flags & SAMPLE_T4:
				data = f.read(2)
				if not len(data): break
				unpacked = struct.unpack('<H', data)[0]

				rawVolt = unpacked*correctionValue;
				r = rawVolt/0.0001;
				kValue = 1/( ( 1/298.15 ) + math.log(r/10000)/thermBValue );
				cValue = kValue - 273.15;

				thisSample['T4']=cValue
				index['T4'].append(len(allSamples))

			allSamples.append(thisSample)

	allSamples[0]['programName']=programName


	'''
	#tach calibrate
	allCalibrateValues = {}
	for tIndex in index['calibrate']:
		tachIndex = allSamples[tIndex]['RPMIndex']
		if tachIndex not in allCalibrateValues:
			allCalibrateValues[tachIndex]=[]
		allCalibrateValues[tachIndex].append(allSamples[tIndex]['RPM'])
	avgValues = {}
	for tIndex in allCalibrateValues:
		avgValues[tIndex]=numpy.mean(numpy.array( allCalibrateValues[tIndex][2:-2] ))
	allAvg = numpy.mean(numpy.array( avgValues.values() ))
	tachCorrection = {}
	for tIndex in avgValues:
		tachCorrection[tIndex]=allAvg/avgValues[tIndex]
	#print 'raw', allCalibrateValues
	#print 'index avg', avgValues
	#print 'all avg', allAvg
	#print 'tach calibration list', tachCorrection
'''


	#test calibrate
	calibrateValues = {}
	indexList = []
	valueList = []
	calibrateCalled = False
	for sampleIndex in index['RPM']:
		#tach values aren't valid until calibrate is called in the program
		if sampleIndex in index['calibrate']: calibrateCalled = True
		if not calibrateCalled: continue

		#keep a running average of all rpm samples
		rpm = allSamples[sampleIndex]['RPM']
		thisIndex = allSamples[sampleIndex]['RPMIndex']
		indexList.append( thisIndex )
		valueList.append( rpm )
		#once the running buffer is full drop off the oldest sample
		if len(indexList)> pulsePerRev:
			indexList.pop(0)
			valueList.pop(0)

		thisValue = numpy.mean(numpy.array( valueList ))
		thisError = thisValue/rpm

		index['autoCalibrate'].append(sampleIndex)
		allSamples[sampleIndex]['autoCalibrate']=thisError

		#sanity check error amount, drop the sample from calibration if it's too far out
		#if (thisError <0.5) or (thisError > 1.5):
		#	continue
		if set(range(1,pulsePerRev+1)) ==  set(indexList):
			if thisIndex not in calibrateValues.keys():
				calibrateValues[thisIndex]=[]
			calibrateValues[thisIndex].append(thisError)


	print 'calib min max med mean stdeviation'
	for cIndex in calibrateValues:
		r=calibrateValues[cIndex]
		print cIndex, min(r), max(r), (numpy.median(numpy.array( r ))), (numpy.mean(numpy.array( r ))), (numpy.std(numpy.array( r )))
		newValues = stdFilter(r, mult=1)
		print 'using', len(newValues),'/', len(r)
		calibrateValues[cIndex] = newValues


	#apply calibration values
	for tIndex in index['RPM']:

		tachIndex = allSamples[tIndex]['RPMIndex']
		if tachIndex in calibrateValues.keys():
			allSamples[tIndex]['RPMRaw']=(allSamples[tIndex]['RPM']/pulsePerRev)
			allSamples[tIndex]['RPM']=(allSamples[tIndex]['RPM']/pulsePerRev)*numpy.mean(numpy.array( calibrateValues[tachIndex] ))    


	# reject obvious noise samples
	
	print 'thrust noise filter...'
	thrustMed = []
	window = []
	for sampleIndex in index['Thrust']:
		window.append( allSamples[sampleIndex]['Thrust'] )
		if len(window)>3:
			window = window[-3:]
		thrustMed.append( numpy.median(window) )

	rejectionCount = 0
	window = []
	newIndexList = []
	for thisIndex, median in enumerate(thrustMed):
		minIndex = thisIndex-2
		maxIndex = thisIndex+2
		if minIndex<0: minIndex = 0
		if maxIndex>len(thrustMed)-1: maxIndex = len(thrustMed)-1

		thisSTD = numpy.std(numpy.array( thrustMed[minIndex:maxIndex] ))
		thisSampleIndex = index['Thrust'][thisIndex]
		thisValue = allSamples[thisSampleIndex]['Thrust']
		distance = abs( median-thisValue)

		if distance>20*thisSTD:
			print 'rejecting sample', getFloatTime(allSamples[thisSampleIndex]['Time']), distance, thisSTD, thisValue
			del allSamples[thisSampleIndex]['Thrust']
			rejectionCount = rejectionCount +1
		else:
			newIndexList.append(thisSampleIndex)

	index['Thrust']=newIndexList

	print 'Total rejections', rejectionCount




	#auto TARE.  based on first 1 sec of log

	print 'auto TARE...'

	lastTime = allSamples[ index['Thrust'][-1] ]['Time']
	lastTime = getFloatTime(lastTime) - 1
	print 'last log time', lastTime
	TARESamples = []
	
	commandCalibrate = True

	minTARETime = 2.5
	maxTARETime = 5

	if commandCalibrate:
		print 'calibrating based on calibration command'
		if ( len(index['calibrate'] )):
			calibStart = index['calibrate'][0]
			calibEnd = index['calibrate'][-1]
			minTARETime = getFloatTime(allSamples[calibStart]['Time']) 
			maxTARETime = getFloatTime(allSamples[calibEnd]['Time']) 

	for sampleIndex in index['Thrust']:
		
		time = allSamples[sampleIndex]['Time']
		roundedTime = getFloatTime(time) 
		#if roundedTime<lastTime: continue
		if roundedTime<minTARETime: continue
		if roundedTime>maxTARETime: break
		
		TARESamples.append(allSamples[sampleIndex]['Thrust'])

	print 'TARE range ', minTARETime, maxTARETime

	'''
	TAREMedian = numpy.median( numpy.array( TARESamples ) )
	cleanedSamples = []
	for sample in TARESamples:
		thisError = sample/TAREMedian

		#sanity check error amount, drop the sample from calibration if it's too far out
		if (thisError <0.5) or (thisError > 2):
			continue
		cleanedSamples.append(sample)
		'''
	cleanedSamples = stdFilter(TARESamples, mult=1)
	print 'using ' , len(cleanedSamples), '/', len(TARESamples)
	TAREAverage = numpy.mean( numpy.array( cleanedSamples ) )
	print TAREAverage

	for sampleIndex in index['Thrust']:
		allSamples[sampleIndex]['Thrust'] = allSamples[sampleIndex]['Thrust'] - TAREAverage


	#interpolate
	for key in index:
		if key == 'RPMIndex' : continue
		if key == 'calibrate' : continue

		seq = index[key]
		for a, b in zip(seq, seq[1:]):
			length = b-a
			if length<2: continue
			start = allSamples[a][key]
			end = allSamples[b][key]
			delta = end-start
			for i in range(1,length):
				allSamples[a+i][key] =start + delta*(float(i)/length)


	if useCache:
		cached = {}
		cached['allSamples'] = allSamples
		cached['index'] = index
		cf = gzip.open(file+'.cache', 'wb' )
		pickle.dump(cached, cf)
		cf.close()

	return allSamples, index

def getInterpolated(indexList, valueList):
	for a, b in zip(indexList, indexList[1:]):
		length = b-a
		if length<2: continue
		start = valueList[a]
		end = valueList[b]
		delta = end-start
		for i in range(1,length):
			valueList[a+i] =start + delta*(float(i)/length)
	return valueList


def getStats(allSample, index):
	x = []
	y = []
	startRange = 5.25 * 1000000
	endRange = 6.75 *1000000

	foundStart = 0
	foundEnd = 0

	smoothV = smoother(avgTaps=6, medTaps=1)
	smoothA = smoother(avgTaps=6, medTaps=1)
	smoothT = smoother(avgTaps=1, medTaps=3)

	for sampleIndex in index['Time']:
		time = allSample[sampleIndex]['Time']
		if not foundStart and time>startRange:
			foundStart = sampleIndex
		if not foundEnd and time>endRange:
			foundEnd = sampleIndex
		if foundStart and foundEnd:
			break

	v=[]
	a=[]
	t=[]
	w=[]
	e=[]
	r=[]

	for sample in allSample[foundStart:foundEnd]:
		v.append(round(sample['Volt'],2))
		a.append(round(sample['Amp'],2))
		watts = sample['Volt']*sample['Amp'] 
		w.append( round(watts, 2) )
		if sample['Thrust']:
			smoothT.add ( sample['Thrust'] )

			t.append(round(smoothT.get(),2))
			e.append(round(smoothT.get()/watts,2))
		if sample['RPM']:
			r.append(int(sample['RPM']))


	v = getMiddleResults(v)
	a = getMiddleResults(a)
	t = getMiddleResults(t)
	w = getMiddleResults(w)
	e = getMiddleResults(e)
	r = getMiddleResults(r)

	print 'stats min max med mean'
	if r: print 'RPM', min(r), max(r), int(numpy.median(numpy.array( r ))), int(numpy.mean(numpy.array( r )))
	if t: print 'thrust', min(t), max(t), numpy.median(numpy.array( t )), round(numpy.mean(numpy.array( t )), 2)
	print 'volts', min(v), max(v), numpy.median(numpy.array( v )), round( numpy.mean(numpy.array( v )), 2 )
	print 'Amps', min(a), max(a), numpy.median(numpy.array( a )),round(numpy.mean(numpy.array( a )), 2)
	print 'watts', min(w), max(w), numpy.median(numpy.array( w )),round(numpy.mean(numpy.array( w )), 2)
	if e: print 'efficiency', min(e), max(e), numpy.median(numpy.array( e )), round(numpy.mean(numpy.array( e )), 2)

	return 

def reject_outliers(samples, m = 2.):
	d = numpy.abs(samples - numpy.median(samples))
	mdev = numpy.median(d)
	s = d/mdev if mdev else 0.
	return samples[s<m]

def stdFilter(samples, mult=1):
	mean = numpy.mean(numpy.array( samples ))
	std = numpy.std(numpy.array( samples )) 
	minVal = mean-(std*mult)
	maxVal = mean+(std*mult)
	print 'found min/max', minVal, maxVal
	cleanedSamples = []
	for sample in samples:
		if sample < minVal: continue
		if sample > maxVal: continue
		cleanedSamples.append(sample)
	return cleanedSamples


def getMiddleResults(samples, factor=0.1):
	return sorted(samples)[int(len(samples)*factor):-int(len(samples)*factor)] #remove the top and bottom 10% of results


def getWatts(sample, index):
	x = []
	y = []

	smoothV = smoother(avgTaps=24, medTaps=1)
	smoothA = smoother(avgTaps=24, medTaps=1)
	smoothT = smoother(avgTaps=6, medTaps=3)
	for sampleIndex in index['Volt']:

		volt = sample[sampleIndex]['Volt']
		amp = sample[sampleIndex]['Amp']
		smoothV.add( volt )
		smoothA.add( amp )

		if sampleIndex not in index['Thrust']: continue

		thrust = sample[sampleIndex]['Thrust']
		smoothT.add ( thrust )
		watts = round(smoothV.get()*smoothA.get()  , 1 )

		y.append(round(smoothT.get(), 2) )
		x.append(watts)

	return x, y

def getEfficiencyOverRPM(sample, index):
	x = []
	y = []

	smoothV = smoother(avgTaps=24, medTaps=1)
	smoothA = smoother(avgTaps=24, medTaps=1)
	smoothT = smoother(avgTaps=6, medTaps=3)
	for sampleIndex in index['Volt']:

		volt = sample[sampleIndex]['Volt']
		amp = sample[sampleIndex]['Amp']
		smoothV.add( volt )
		smoothA.add( amp )

		if sampleIndex not in index['Thrust']: continue

		thrust = sample[sampleIndex]['Thrust']
		smoothT.add ( thrust )
		rpm = sample[sampleIndex]['RPM']

		watts = round(smoothV.get()*smoothA.get()  , 1 )
		if not watts: continue
		y.append(round(smoothT.get(), 2)/watts )
		x.append(rpm)

	return x, y

def getMechanicalPower(sample, index):
	x = []
	y = []

	smoothV = smoother(avgTaps=24, medTaps=1)
	smoothA = smoother(avgTaps=24, medTaps=1)
	smoothT = smoother(avgTaps=6, medTaps=3)
	for sampleIndex in index['Thrust']:
		time = sample[sampleIndex]['Time']

		volt = sample[sampleIndex]['Volt']
		amp = sample[sampleIndex]['Amp']
		smoothV.add( volt )
		smoothA.add( amp )

		if sampleIndex not in index['Thrust']: continue

		thrust = sample[sampleIndex]['Thrust']
		smoothT.add ( thrust )
		rpm = sample[sampleIndex]['RPM']

		if not rpm: continue

		mechWatts = smoothT.get() * (rpm * ((2*math.pi)/60) )
		watts = round(smoothV.get()*smoothA.get()  , 1 )
		if not watts: continue
		y.append( round(mechWatts, 2) )
		x.append( getFloatTime(time) )

	return x, y

def getTestWatts(sample, index):
	x = []
	y = []

	smoothV = smoother(avgTaps=24, medTaps=1)
	smoothA = smoother(avgTaps=24, medTaps=1)
	for sampleIndex in index['Volt']:
		time = sample[sampleIndex]['Time']

		volt = sample[sampleIndex]['Volt']
		amp = sample[sampleIndex]['Amp']
		smoothV.add( volt )
		smoothA.add( amp )
		
		watts = smoothV.get()*smoothA.get()
		if not watts: continue
		y.append(round(watts, 2) )
		x.append( getFloatTime(time) )

	return x, y

def getMechanicalEff(sample, index):
	x = []
	y = []

	smoothV = smoother(avgTaps=24, medTaps=1)
	smoothA = smoother(avgTaps=24, medTaps=1)
	smoothT = smoother(avgTaps=6, medTaps=3)
	for sampleIndex in index['Volt']:
		time = sample[sampleIndex]['Time']
		roundedTime = getFloatTime(time) 

		if roundedTime<11: continue
		if roundedTime>15: continue

		volt = sample[sampleIndex]['Volt']
		amp = sample[sampleIndex]['Amp']
		smoothV.add( volt )
		smoothA.add( amp )

		if sampleIndex not in index['Thrust']: continue

		thrust = sample[sampleIndex]['Thrust']
		smoothT.add ( thrust )
		rpm = sample[sampleIndex]['RPM']

		if not rpm: continue
		
		mechWatts = smoothT.get() * (rpm * ((2*math.pi)/60) )
		watts = smoothV.get()*smoothA.get()
		if not watts: continue
		y.append(round(mechWatts/watts, 2) )
		x.append(roundedTime)

	return x, y

def getTorqueOverRPM(sample, index):
	x = []
	y = []
	z = []

	smoothV = smoother(avgTaps=25, medTaps=1)
	smoothA = smoother(avgTaps=25, medTaps=1)
	smoothT = smoother(avgTaps=3, medTaps=5)
	for sampleIndex in index['Volt']:
		time = sample[sampleIndex]['Time']
		roundedTime = getFloatTime(time) 

		if roundedTime<9.5: continue
		if roundedTime>13: continue

		volt = sample[sampleIndex]['Volt']
		amp = sample[sampleIndex]['Amp']
		smoothV.add( volt )
		smoothA.add( amp )

		if sampleIndex not in index['Thrust']: continue

		thrust = sample[sampleIndex]['Thrust']
		smoothT.add ( thrust )
		rpm = sample[sampleIndex]['RPM']

		if not rpm: continue
		
		mechWatts = smoothT.get() * (rpm * ((2*math.pi)/60) )
		watts = smoothV.get()*smoothA.get()
		if not watts: continue

		y.append(round(smoothT.get(), 4) )
		x.append(rpm)
		z.append(round(mechWatts/watts, 2) )

	return x, y, z, sample[0]['programName']

def getEfficiencyOverThrottle(sample, index):
	x = []
	y = []

	smoothV = smoother(avgTaps=24, medTaps=1)
	smoothA = smoother(avgTaps=24, medTaps=1)
	smoothT = smoother(avgTaps=6, medTaps=3)
	for sampleIndex in index['Volt']:

		volt = sample[sampleIndex]['Volt']
		amp = sample[sampleIndex]['Amp']
		smoothV.add( volt )
		smoothA.add( amp )

		if sampleIndex not in index['Thrust']: continue

		thrust = sample[sampleIndex]['Thrust']
		smoothT.add ( thrust )

		throttle = sample[sampleIndex]['Motor Command']

		watts = round(smoothV.get()*smoothA.get()  , 1 )
		if not watts: continue
		y.append(round(smoothT.get(), 2)/watts )
		x.append(throttle)

	return x, y

def getThrust(sample, index):
	# thrust / RPM
	x = []
	y = []
	smooth = smoother(avgTaps=1, medTaps=1)
	tSmooth = smoother(avgTaps=1, medTaps=1)
	for sampleIndex in index['Thrust']:
		rpm = sample[sampleIndex]['RPM']
		time = sample[sampleIndex]['Time']
		thrust = sample[sampleIndex]['Thrust']
		if rpm > 60000: continue
		if not rpm: continue
		smooth.add( rpm )
		smoothedValue = round(smooth.get(), 3 )
		tSmooth.add( thrust )
		tSmoothedValue = round(tSmooth.get(), 3 )
		x.append(smoothedValue)
		y.append(tSmoothedValue)

	return x, y

def getThrustFit(sample, index):
	# thrust / RPM
	x = []
	y = []
	smooth = smoother()
	#sample, index = readLog('C:\\Users\\markm\\Documents\\Drones\\PropBenchmarks\\bladeShapes\\rxTri.txt')
	for sampleIndex in index['RPM']:
		rpm = sample[sampleIndex]['RPM']
		time = sample[sampleIndex]['Time']
		thrust = sample[sampleIndex]['Thrust']
		if rpm > 45000: continue

		smooth.add( rpm )
		smoothedValue = round(smooth.get(), 3 )
		x.append(smoothedValue)
		y.append(thrust)

	xTrim = x[:int(len(x)*0.5)]
	yTrim = y[:int(len(y)*0.5)]
	#Calculate trendline
	x = numpy.linspace(0, 40000, num=len(xTrim))
	order = 2
	coeffs = poly.polyfit(xTrim,yTrim, order)
	y = poly.polyval(x, coeffs)

	return x, y

def getTestThrust(sample, index):
	# thrust / RPM
	x = []
	y = []
	smooth = smoother(avgTaps=1, medTaps=1)
	for sampleIndex in index['Thrust']:
		time = sample[sampleIndex]['Time']
		thrust = sample[sampleIndex]['Thrust']
		smooth.add( thrust )
		smoothedValue =  round(smooth.get(), 4 )
		x.append( getFloatTime(time) )
		y.append(smoothedValue)
	return x, y

def getThrottleThrust(sample, index):
	# thrust / RPM
	x = []
	y = []
	smooth = smoother(avgTaps=1, medTaps=3)
	for sampleIndex in index['Thrust']:
		throttle = sample[sampleIndex]['Motor Command']
		thrust = sample[sampleIndex]['Thrust']
		smooth.add( thrust )
		smoothedValue =  round(smooth.get(), 3 )
		x.append(throttle )
		y.append(smoothedValue)
	return x, y

def getRpmOverThrottle(sample, index):
	# thrust / RPM
	x = []
	y = []
	smooth = smoother(avgTaps=2, medTaps=1)

	for sampleIndex in index['RPM']:
		throttle = sample[sampleIndex]['Motor Command']
		rpm = sample[sampleIndex]['RPM']
		if rpm > 65000: 
			continue
		x.append( throttle )
		smooth.add( rpm )
		thisValue = smooth.get()
		y.append(rpm)
	return x, y

def getTestRpm(sample, index, deltaMode=False):
	# thrust / RPM
	x = []
	y = []
	smooth = smoother(avgTaps=2, medTaps=1)
	dsmooth = smoother(avgTaps=2, medTaps=1)

	lastGoodTime = 0
	lastValue = 0
	for sampleIndex in index['RPM']:
		time = sample[sampleIndex]['Time']
		rpm = sample[sampleIndex]['RPM']
		if rpm > 65000: 
			print 'False Trigger', lastGoodTime, time, time-lastGoodTime
			continue
		x.append( getFloatTime(time) )
		smooth.add( rpm )
		thisValue = smooth.get()
		if deltaMode:
			dsmooth.add( float(thisValue-lastValue)/(float(time-lastGoodTime)/1000)  )
			y.append( dsmooth.get() )
			lastGoodTime = time
			lastValue = thisValue
		else:
			y.append(rpm)
	return x, y

def getTestRpmError(sample, index, deltaMode=False):
	x = []
	y = []

	for sampleIndex in index['autoCalibrate']:
		time = sample[sampleIndex]['Time']
		volt = sample[sampleIndex]['autoCalibrate']
		x.append( getFloatTime(time) )
		y.append(volt)
	return x, y

def getTestVoltsRaw(sample, index):
	x = []
	y = []

	for sampleIndex in index['Volt']:
		time = sample[sampleIndex]['Time']
		volt = sample[sampleIndex]['Volt']
		x.append( getFloatTime(time) )
		y.append(volt)
	return x, y

def getTestT1Raw(sample, index, deltaMode=False):
	x = []
	y = []
	lastGoodTime = 0
	lastValue = 0
	dsmooth = smoother(avgTaps=70, medTaps=1)

	for sampleIndex in index['T1']:
		time = sample[sampleIndex]['Time']
		T1 = sample[sampleIndex]['T1']
		x.append( getFloatTime(time) )


		if deltaMode:
			dsmooth.add( 1000*(float(T1-lastValue)/(float(time-lastGoodTime)/1000))  )
			y.append( dsmooth.get() )
			lastGoodTime = time
			lastValue = T1
		else:
			y.append(T1)

	return x, y

def getThrustOverT1(sample, index):
	x = []
	y = []
	for sampleIndex in index['Thrust']:
		T1 = sample[sampleIndex]['T1']
		thrust = sample[sampleIndex]['Thrust']
		x.append(T1 )
		y.append(thrust)
	return x, y

def getThrustOverV(sample, index):
	x = []
	y = []
	for sampleIndex in index['Thrust']:
		volt = sample[sampleIndex]['Volt']
		thrust = sample[sampleIndex]['Thrust']
		x.append(volt )
		y.append(thrust)
	return x, y

def getCommandRaw(sample, index):
	x = []
	y = []
	for sampleIndex in index['Motor Command']:
		time = sample[sampleIndex]['Time']
		T1 = sample[sampleIndex]['Motor Command']
		x.append( getFloatTime(time) )
		y.append(T1)
	return x, y

def getTestAmpsRaw(sample, index):
	x = []
	y = []
	for sampleIndex in index['Amp']:
		time = sample[sampleIndex]['Time']
		amp = sample[sampleIndex]['Amp']
		x.append( getFloatTime(time) )
		y.append(amp)
	return x, y

def getTestVolts(sample, index):
	x = []
	y = []

	smooth = smoother(avgTaps=24, medTaps=6)
	lastTime = 0
	for sampleIndex in index['Volt']:
		time = sample[sampleIndex]['Time']
		volt = sample[sampleIndex]['Volt']
		smooth.add( volt )
		if time-lastTime > MIN_SAMPLE_TIME:
			x.append( getFloatTime(time) )
			y.append(smooth.get())
			lastTime = time
	return x, y

def getTestAmps(sample, index):
	x = []
	y = []

	smooth = smoother(avgTaps=24, medTaps=6)
	lastTime = 0
	for sampleIndex in index['Amp']:
		time = sample[sampleIndex]['Time']
		amp = sample[sampleIndex]['Amp']
		smooth.add( amp )
				
		if time-lastTime > MIN_SAMPLE_TIME:
			x.append( getFloatTime(time) )
			y.append(smooth.get())
			lastTime = time
	return x, y

def getTestRpmRAW(sample, index, deltaMode=False):
	# thrust / RPM
	x = []
	y = []
	lastGoodTime=0
	lastValue=0
	for sampleIndex in index['RPM']:
		time = sample[sampleIndex]['Time']
		rpm = sample[sampleIndex]['RPMRaw']
		x.append( getFloatTime(time) )

		thisValue = rpm
		if deltaMode:
			y.append( float(thisValue-lastValue)/(float(time-lastGoodTime)/1000) )
			lastGoodTime = time
			lastValue = thisValue
		else:
			y.append(thisValue)

	return x, y

def getLoad(sample, index, unloadedRPM):
	# Motor Load
	x = []
	y = []
	smooth = smoother()
	#sample, index = readLog('C:\\Users\\markm\\Documents\\Drones\\PropBenchmarks\\bladeShapes\\rxTri.txt')
	for sampleIndex in index['RPM']:
		value = sample[sampleIndex]['RPM']
		time = sample[sampleIndex]['Time']

		if value > 60000: continue
		x.append( getFloatTime(time) )
		smooth.add( value )
		smootedValue = round(smooth.get(), 3 )
		if sampleIndex >= len(unloadedRPM): continue
		if unloadedRPM[sampleIndex]==None: continue 
		y.append(100- (smootedValue/unloadedRPM[sampleIndex])*100 )
	return x, y

def getUnloadedBaseline(logPath):
	sample, index = readBinaryLog(logPath)

	unloadedRPM = [None]*len(sample)
	unloadedIndex = []
	smooth = smoother(avgTaps=4, medTaps=1)
	for sampleIndex in index['RPM']:
		value = sample[sampleIndex]['RPM']

		if value > 60000: continue
		smooth.add( value )
		unloadedRPM[sampleIndex] = round(smooth.get(), 3 )
		unloadedIndex.append(sampleIndex)

	getInterpolated(unloadedIndex, unloadedRPM)
	return unloadedRPM

def getFloatTime(time):
		return round(float(time)/1000000, TIMEROUNDING) 

def buildFigure(dataList, labelList, deltaMode, chartTitle=None, mode=None, patchLoad=None):
	colorsSource = ['steelblue', 'teal', 'indigo', 'greenyellow', 'gray', 'fuchsia', 'yellow', 'black', 'purple', 'orange', 'green', 'blue','red']
	colors = copy.copy(colorsSource)
	xLabel = labelList['x']
	yLabel = labelList['y']
	yScale = labelList['yScale']
	if deltaMode:
		yScale = labelList['yScaleDelta']
	
	deltaString = ''
	if deltaMode:
		deltaString = ' - Delta'

	outputFile = './output/'+mode+deltaString+'.html'
	outputTitle = mode+deltaString
	if chartTitle:
		outputTitle = chartTitle

	output_file( outputFile, title=outputTitle, mode='inline' )

	foundZ = False

	for item in dataList[::-1]:
		if item['z']:
			foundZ = True
	tooltipList = [
			#("index", "$index"),
			(xLabel, "@x{1.11}"),
			(yLabel, "@y{1.11}"),
		]

	if foundZ:
		tooltipList.append(('z', "@z{1.11}") )

	hover = HoverTool(
		tooltips = tooltipList,
		#mode='vline',
	)



	p = figure(
		width=1520, plot_height=880,
		tools=[hover,'pan','box_zoom','wheel_zoom', 'reset','crosshair', 'tap'],#"resize,pan,wheel_zoom,box_zoom,reset,box_select,lasso_select,hover",
		active_scroll='wheel_zoom',
		y_range=[0, yScale],
		x_axis_label=xLabel,# y_axis_label=yLabel,
		output_backend="webgl",
		title=outputTitle
	)
	

	defaultRange = 'default_range'
	p.extra_y_ranges.update( {defaultRange: Range1d(start=0, end=yScale)} )
	p.add_layout(LinearAxis(y_range_name=defaultRange,  axis_label=yLabel), 'left')


	#mapperColors = ["#75968f", "#a5bab7", "#c9d9d3", "#e2e2e2", "#dfccce", "#ddb7b1", "#cc7878", "#933b41", "#550b1d"]
	#mapperColors = ["#d7191c", "#D3272D", "#CD3C46", "#C45E6F", "#BA8098", "#b0a3c2", "#929FC9", "#6C99D2", "#4694DB", "#3791DF", "#198de6"]
	#mapperColors = ["#d7191c", "#CF353D", "#C7505E", "#CF7E8C", "#CDA0B1", "#cac2d6", "#9EB5DA", "#72A8DE", "#459AE2", "#198de6"]
	mapperColors = ["#d7191c", "#CF353D", "#C7505E", "#CF7E8C", "#CDA0B1", "#cac2d6", "#9EB5DA", "#72A8DE", "#459AE2", "#198de6"]
	#mapperColors = ["#d7191c",  "#ff0000",  "#000000",  "#00ff00", "#198de6"]
	mapper = LinearColorMapper(palette=mapperColors, low=.0, high=1)
	mapperLegend = LinearColorMapper(palette=mapperColors, low=.0, high=100)

	if outputTitle == 'Torque Over RPM':
		allRanges = []
		for item in dataList:
			throttleValue = int(item['programName'].split('_')[0])
			smooth = smoother(avgTaps=3, medTaps=1)
			smoothT = smoother(avgTaps=1, medTaps=3)
			newZ = []
			newY = []
			for value in item['z']:
				smooth.add(value)
				newZ.append( smooth.get() )
			count = 0
			for value in item['y']:
				smoothT.add(value)
				#if value < 0: print 'under',  smoothT.get(), smoothT.medAcc, smoothT.avgAcc, count
				count = count +1
				newY.append( smoothT.get() )
			#item['z']=newZ

			range = {}
			topValue = newZ[-1]
			band = int(topValue*10)
			range[band]={}
			range['throttleValue']=throttleValue

			range[band]['start']=[item['x'][-1],newY[-1]]
			#for index in xrange(band, -1, -1):
			for index in xrange(0,band, 1):
				range[index]={}
				range[index]['start']=[item['x'][-1],newY[-1]]
				range[index]['end']=[item['x'][-1],newY[-1]]

			for index in xrange(len(item['z'] )-1, -1, -1): # count top down
			#for index in xrange(0, len(item['z'] ), 1): # count bottom up
				thisValue = item['z'][index]
				if thisValue > 1: continue
				if int(thisValue*10) > band:
					range[band]['end']=[item['x'][index],newY[index]]
					band = int(thisValue*10)
					range[band]={}
					range[band]['start']=[item['x'][index],newY[index]]
			range[band]['end']=[item['x'][0],newY[0]]

			for index in xrange(band+1, 11 ):
				range[index]={}
				range[index]['start']=[item['x'][0],newY[0]]
				range[index]['end']=[item['x'][0],newY[0]]
			allRanges.append(range)
			#item['range'] = range

		allMin = 10
		for range in allRanges:
			allMin = min(min(range.keys()), allMin)
		print 'Lowest range', allMin

		shapeCoords = {}
		for shapeRange in xrange(0,11):
			for range in allRanges:
				thisMin = min(range.keys())
				thisMax = max(range.keys())
				if shapeRange not in range.keys():
					continue
					range[shapeRange] = {}
					if shapeRange<thisMin:
						range[shapeRange]['start'] = range[thisMin]['start']
						range[shapeRange]['end'] = range[thisMin]['start']
					else:
						range[shapeRange]['start'] = range[thisMax]['end']
						range[shapeRange]['end'] = range[thisMax]['end']
				if shapeRange not in shapeCoords.keys():
					shapeCoords[shapeRange] = []
				shapeCoords[shapeRange].append( [range[shapeRange]['start'], range[shapeRange]['end'], range['throttleValue']] )

		patches = {}
		patchDump = {}

		for index in shapeCoords:
			shapeCoords[index].sort(key=lambda x: x[2]  )

		for shapeRange in shapeCoords.keys():
			patches[shapeRange] = {}
			patchDump[shapeRange] = []
			patches[shapeRange]['x']=[]
			patches[shapeRange]['y']=[]

			for index in xrange(0, len(shapeCoords[shapeRange])):
				x = int(shapeCoords[shapeRange][index][0][0])
				y = round(shapeCoords[shapeRange][index][0][1],4)
				patches[shapeRange]['x'].append( x )
				patches[shapeRange]['y'].append( y )
				patchDump[shapeRange].append( [x,y] )

			for index in xrange(len(shapeCoords[shapeRange])-1, -1, -1):
				x = int(shapeCoords[shapeRange][index][1][0])
				y = round(shapeCoords[shapeRange][index][1][1],4)
				patches[shapeRange]['x'].append( x )
				patches[shapeRange]['y'].append( y )
				patchDump[shapeRange].append( [x,y] )

		patchFile = open('last.patch', 'w')
		json.dump(patchDump, patchFile, sort_keys=True, indent=4, separators=(',', ': '))
		patchFile.close()

	if patchLoad:
		patches = {}
		for shapeRange in sorted(patchLoad.keys()):
			thisRange = int(shapeRange)
			patches[thisRange] = {}
			patches[thisRange]['x']=[]
			patches[thisRange]['y']=[]
			for index in xrange(0, len(patchLoad[shapeRange])):
				patches[thisRange]['x'].append( patchLoad[shapeRange][index][0] )
				patches[thisRange]['y'].append( patchLoad[shapeRange][index][1] )


	for item in dataList[::-1]:
		if not colors:
			colors = copy.copy(colorsSource)

		print 'creating plot for', item['label'], item['mode']
		thisRange = defaultRange
		if item['extraRange']:
			rangeName = item['label'] + '_range'
			print "made range", rangeName, item['extraRange']
			p.extra_y_ranges.update( {rangeName: Range1d(start=0, end=item['extraRange'])} )
			p.add_layout(LinearAxis(y_range_name=rangeName, axis_label=item['extraLabel']), 'left')
			thisRange = rangeName

		data = {
			'x':item['x'],
			'y':item['y']
			}

		if item['z']:
			data['z']= item['z']
			data['scatterSize']=[i * 8 for i in item['z']]
			data['color']=[i  for i in item['z']]



		source = ColumnDataSource( data=data)

		if item['mode']=='line':
			p.line('x', 'y', source=source, legend=item['label'], color=colors.pop(), line_width=3, y_range_name=thisRange)

		else:
			scatterSize = 8
			if item['z']:
				#scatterSize = 'scatterSize'
				thisColor = {'field': 'z', 'transform': mapper}
			else:
				thisColor = colors.pop()
			p.scatter('x', 'y', source=source, legend=item['label'], color=thisColor, size=scatterSize, y_range_name=thisRange)

	p.legend.location = "top_left"
	p.legend.click_policy="hide"

	if outputTitle == 'Torque Over RPM':
		color_bar = ColorBar(color_mapper=mapperLegend, major_label_text_font_size="8pt",
                     ticker=BasicTicker(desired_num_ticks=len(colors)),
                     formatter=PrintfTickFormatter(format="%d%%"),
                     label_standoff=6, border_line_color=None, 
                     height=500, location=(-80, 0))
		p.add_layout(color_bar, 'right')

		for index in patches:
			if index>len(mapperColors)-1:
				thisColor = mapperColors[-1]
			else:
				thisColor = mapperColors[index]
			p.patch( patches[index]['x'], patches[index]['y'], alpha=0.5, line_width=2, fill_color=thisColor)

	callback = CustomJS(code="""
	// the event that triggered the callback is cb_obj:
	// The event type determines the relevant attributes
	if (typeof coords == 'undefined') {
		coords = [];
	}
	coords.push( [ Math.round(cb_obj.x), +cb_obj.y.toFixed(2) ] );
	console.log('Tap event occured at x-position: ' + cb_obj.x + ', '+ cb_obj.y);
	""")

	tapCallback = CustomJS(code="""
	if (typeof coords == 'undefined') {
		coords = [];
	}
	var srcIndex = cb_data.source.selected['1d'].indices[0];
	var d1 = cb_data.source.data;
	var x = d1['x'][srcIndex];
	var y = d1['y'][srcIndex];
	console.log('TapTool event occured at x-position: ' + x + ', '+ y);
	coords.push( [ Math.round(x), +y.toFixed(2) ] );

	""")

	#p.js_on_event(events.Tap, callback)

	taptool = p.select(type=TapTool)
	taptool.callback = tapCallback

	show(p)
	reset_output()

