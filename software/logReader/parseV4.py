import gzip
import pickle
import os
import math

import numpy

from . import util
from . import filters

useCache = False

SAMPLE_TIME	= 1<<0
SAMPLE_MOTORCOMMAND	= 1<<1
SAMPLE_TACH = 1<<2
SAMPLE_VOLT = 1<<3
SAMPLE_AMP = 1<<4
SAMPLE_THRUST = 1<<5
SAMPLE_T1 = 1<<6
SAMPLE_TACH_INDEX = 1<<7
SAMPLE_CALIBRATE = 1<<8
SAMPLE_AUXCOMMAND = 1<<9
SAMPLE_MARKER = 1<<10


def readBinaryLog(file, shortLoad=None):
	import struct
	print 'parsing log v4', file

	allKeys = ['RPM', 'RPMRAW', 'RPMSingle', 'RPMIndex', 'calibrate', 'Volt', 'Amp', 'Thrust','Motor Command','Aux Command', 'Time', 'T1', 'T2', 'T3', 'T4', 'autoCalibrate', 'Marker']
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
		adcMax = 65535
		vref = 3.0
		dataStart = None
		vCalibrationFactor = 3665 #3s mode
		vCalibrationOffset = 115 
		aCalibrationFactor = 730.0
		aCalibrationOffset = 296.0
		loadCellCalib = 200.9647
		programName = None
		motorPully = 1
		drivePully = 1

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
			if 'vCalibrate:' in line:
				vCalibrationFactor = float(line.split(':')[-1])
				print 'set vCalibration', vCalibrationFactor
			if 'vOffset:' in line:
				vCalibrationOffset = float(line.split(':')[-1])
			if 'aCalibrate:' in line:
				aCalibrationFactor = float(line.split(':')[-1])
			if 'aOffset:' in line:
				aOffset = float(line.split(':')[-1])

			if 'motorPully:' in line:
				temp = float(line.split(':')[-1])
				if temp>1: motorPully = temp
			if 'drivePully:' in line:
				temp = float(line.split(':')[-1])
				if temp>1: drivePully = temp

			if 'loaded program:' in line:
				programName = line.split(':')[-1].strip()

			if line == 'Data Start:\n':
				dataStart = f.tell()
				break
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

			if flags & SAMPLE_AUXCOMMAND:
				data = f.read(2)
				if not len(data): break
				unpacked = struct.unpack('<h', data)[0]
				thisSample['Aux Command']=unpacked
				index['Aux Command'].append(len(allSamples))

			if flags & SAMPLE_TACH:
				data = f.read(4)
				if not len(data): break
				unpacked = struct.unpack('<L', data)[0]
				if unpacked == 0:
					rpm = -1
				else:
					rpm = ((1000000.0/unpacked)*60 ) * (drivePully/motorPully )
				thisSample['RPM']=rpm
				index['RPM'].append(len(allSamples))
				index['RPMRAW'].append(len(allSamples))
			
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
				adcVolt = unpacked #* correctionValue
				sensorVolt = (adcVolt+vCalibrationOffset)/vCalibrationFactor
				thisSample['VoltADC']=adcVolt
				thisSample['Volt']=sensorVolt
				index['Volt'].append(len(allSamples))

			if flags & SAMPLE_AMP:
				data = f.read(2)
				if not len(data): break
				unpacked = struct.unpack('<H', data)[0]
				adcVolt = unpacked #* correctionValue
				sensorAmps = (adcVolt+aCalibrationOffset)/aCalibrationFactor
				thisSample['AmpADC']=adcVolt
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

				thisSample['ThrustADC']=unpacked
				unpacked = unpacked/loadCellCalib
				#unpacked = unpacked*21.5
				thisSample['Thrust']=unpacked
				index['Thrust'].append(len(allSamples))

			if flags & SAMPLE_T1:
				data = f.read(1)
				if not len(data): break
				unpacked = struct.unpack('<B', data)[0]
				tempChannel = unpacked
				data = f.read(2)
				if not len(data): break
				unpacked = struct.unpack('<H', data)[0]

				rawVolt = unpacked*correctionValue;
				r = rawVolt/0.0001;
				kValue = 1/( ( 1/298.15 ) + math.log(r/10000)/thermBValue );
				cValue = kValue - 273.15;

				thisSample['T'+str(tempChannel)]=cValue
				index['T'+str(tempChannel)].append(len(allSamples))

			if flags & SAMPLE_MARKER:
				data = f.read(1)
				if not len(data): break
				unpacked = struct.unpack('<B', data)[0]
				markerIndex = unpacked
				thisSample['Marker']=markerIndex
				index['Marker'].append(len(allSamples))



			allSamples.append(thisSample)

			if shortLoad:
				if util.getFloatTime( thisSample['Time'] ) > shortLoad:
					break

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

	lastTime = None
	timeDeltas = []
	for sampleIndex in index['Time'][:-1]:
		thisTime = allSamples[sampleIndex]['Time']
		if not lastTime:
			lastTime = thisTime
			continue

		timeDeltas.append( util.getFloatTime( thisTime - lastTime ) )
		lastTime = thisTime

	allSamples[0]['sampleTime']=numpy.mean(numpy.array( timeDeltas ) )

	print 'detected sample rate', 1/allSamples[0]['sampleTime']
	#test calibrate
	calibrateValues = {}
	indexList = []
	valueList = []
	calibrateCalled = False
	for sampleIndex in index['RPM']:
		#tach values aren't valid until calibrate is called in the program
		#if sampleIndex in index['calibrate']: calibrateCalled = True
		#if not calibrateCalled: continue

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
		newValues = filters.stdFilter(r, mult=1)
		print 'using', len(newValues),'/', len(r)
		calibrateValues[cIndex] = newValues


	#apply calibration values

	rpmAccum = []
	for tIndex in index['RPM']:
		tachIndex = allSamples[tIndex]['RPMIndex']

		if tachIndex in calibrateValues.keys():
			allSamples[tIndex]['RPMRAW']=(allSamples[tIndex]['RPM']/pulsePerRev)
			allSamples[tIndex]['RPM']=(allSamples[tIndex]['RPM']/pulsePerRev)*numpy.mean(numpy.array( calibrateValues[tachIndex] ))    
			
			rpmAccum.append( allSamples[tIndex]['RPMRAW'] )
			if tachIndex == 1:
				allSamples[tIndex]['RPMSingle'] = numpy.mean(rpmAccum)
				index['RPMSingle'].append(tIndex)
				rpmAccum = []


	# reject obvious noise samples

	filters.highValueIndexFilter(index, allSamples, 'RPM', cutoff=80000)

	print 'tach noise filter...'
	#stdIndexFilter(index, allSamples, 'RPM', windowSize=3, distanceMult=10)
	#stdIndexFilter(index, allSamples, 'RPM', windowSize=3, distanceMult=20)
	#stdIndexFilter(index, allSamples, 'RPM', windowSize=10, distanceMult=10)

	print 'thrust noise filter...'
	filters.stdIndexFilter(index, allSamples, 'Thrust', windowSize=3, distanceMult=20)

	#lowpass filter
	filters.lowpassIndexFilter(index, allSamples, 'Amp', order=1, cutoff=4)
	filters.lowpassIndexFilter(index, allSamples, 'Volt', order=1, cutoff=4)
	#if len(index['RPM']) > 1:
	#	filters.lowpassIndexFilter(index, allSamples, 'RPM', order=2, cutoff=100)
	if len(index['Thrust']) > 1:
		filters.lowpassIndexFilter(index, allSamples, 'Thrust', order=2, cutoff=8)
	if len(index['T4']) > 1:
		filters.lowpassIndexFilter(index, allSamples, 'T4', order=1, cutoff=1)

	#for sampleIndex in index['Thrust']:
	#	allSamples[sampleIndex]['ThrustF'] = allSamples[sampleIndex]['Thrust']

	for sampleIndex in index['RPM']:
		allSamples[sampleIndex]['RPMF'] = allSamples[sampleIndex]['RPM']

	index['RPMF']=index['RPM']


	#auto TARE.

	print 'auto TARE...'

	lastTime = allSamples[ index['Thrust'][-1] ]['Time']
	lastTime = util.getFloatTime(lastTime) - 1
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
			minTARETime = util.getFloatTime(allSamples[calibStart]['Time']) 
			maxTARETime = util.getFloatTime(allSamples[calibEnd]['Time']) 

	for sampleIndex in index['Thrust']:
		
		time = allSamples[sampleIndex]['Time']
		roundedTime = util.getFloatTime(time) 
		#if roundedTime<lastTime: continue
		if roundedTime<minTARETime: continue
		if roundedTime>maxTARETime: break
		
		TARESamples.append(allSamples[sampleIndex]['ThrustF'])

	print 'TARE range ', minTARETime, maxTARETime

	cleanedSamples = filters.stdFilter(TARESamples, mult=1)
	print 'using ' , len(cleanedSamples), '/', len(TARESamples)
	TAREAverage = numpy.mean( numpy.array( cleanedSamples ) )
	print TAREAverage

	for sampleIndex in index['Thrust']:
		allSamples[sampleIndex]['Thrust'] = allSamples[sampleIndex]['Thrust'] - TAREAverage
		allSamples[sampleIndex]['ThrustF'] = allSamples[sampleIndex]['ThrustF'] - TAREAverage

	# calculate thrust residuals
	for sampleIndex in index['Thrust']:

		allSamples[sampleIndex]['ThrustResidual'] = allSamples[sampleIndex]['Thrust'] - allSamples[sampleIndex]['ThrustF']
	index['ThrustResidual']= index['Thrust']
	index['ThrustF']= index['Thrust']


	#interpolate
	for key in index:
		if key == 'RPMIndex' : continue
		if key == 'RPMRAW' : continue
		if key == 'calibrate' : continue
		if key == 'Marker' : continue
		if not len(index[key]) : continue
		print 'interpolating', key

		seq = index[key]
		for a, b in zip(seq, seq[1:]):
			length = b-a
			if length<2: continue
			start = allSamples[a][key]
			end = allSamples[b][key]
			delta = end-start
			for i in range(1,length):
				allSamples[a+i][key] =start + delta*(float(i)/length)

		#fill the head of the sample with the first sample value
		for sampleIndex in range( index[key][0] ):
			allSamples[sampleIndex][key] = allSamples[index[key][0]][key]
		#fill the tail of the sample with the last sample value
		for sampleIndex in range( len(allSamples) - index[key][-1] ):
			allSamples[sampleIndex+index[key][-1]][key] = allSamples[index[key][-1]][key]



	if useCache:
		cached = {}
		cached['allSamples'] = allSamples
		cached['index'] = index
		cf = gzip.open(file+'.cache', 'wb' )
		pickle.dump(cached, cf)
		cf.close()

	return allSamples, index
