
import numpy
import scipy.signal as signal


def highValueIndexFilter(index, allSamples, key, cutoff=1):
	rejectionCount = 0
	newIndexList = []
	for sampleIndex in index[key]:
		if allSamples[sampleIndex][key] < cutoff:
			newIndexList.append(sampleIndex)
		else:
			del allSamples[sampleIndex][key]
			rejectionCount = rejectionCount +1
	
	index[key]=newIndexList

	print 'Value filter: Total', key, 'rejections', rejectionCount

def lowpassIndexFilter(index, allSamples, key, order=1, cutoff=10):
	sampleRate = 1/allSamples[0]['sampleTime']
	cutoffValue = cutoff/sampleRate
	print 'creating filtered index ', key+'F', len(index[key]), cutoffValue
	temp = []
	for sampleIndex in index[key]:
		temp.append( allSamples[sampleIndex][key] )

	filtered = butterFilter(temp, order=order, cutoff=cutoffValue)
	for filteredIndex in range( len(temp) ):
		sampleIndex = index[key][filteredIndex]
		allSamples[sampleIndex][key+'F']=filtered[filteredIndex]

	index[key+'F']=index[key]

def stdIndexFilter(index, allSamples, key, windowSize=3, distanceMult=20):
	tachMed = []
	window = []
	for sampleIndex in index[key]:
		window.append( allSamples[sampleIndex][key] )
		if len(window)>windowSize:
			window = window[-windowSize:]
		tachMed.append( numpy.median(window) )

	rejectionCount = 0
	window = []
	newIndexList = []
	for thisIndex, median in enumerate(tachMed):
		minIndex = thisIndex-2
		maxIndex = thisIndex+2
		if minIndex<0: minIndex = 0
		if maxIndex>len(tachMed)-1: maxIndex = len(tachMed)-1

		thisSTD = numpy.std(numpy.array( tachMed[minIndex:maxIndex] ))
		thisSampleIndex = index[key][thisIndex]
		thisValue = allSamples[thisSampleIndex][key]
		distance = abs( median-thisValue)

		if(False):
			thisTime = util.getFloatTime(allSamples[thisSampleIndex]['Time'])
			if (thisTime > 7.531) and (thisTime < 7.536 ):
				print key, 'sample at', util.getFloatTime(allSamples[thisSampleIndex]['Time']), 'dist:', distance, 'med:', median, 'std:', thisSTD, 'value:', thisValue
				if distance>10*thisSTD:
					print 'rejected'


		if distance>distanceMult*thisSTD:
			#print 'rejecting sample', util.getFloatTime(allSamples[thisSampleIndex]['Time']), distance, thisSTD, thisValue
			del allSamples[thisSampleIndex][key]
			rejectionCount = rejectionCount +1
		else:
			newIndexList.append(thisSampleIndex)

	index[key]=newIndexList

	print 'Total', key, 'rejections', rejectionCount

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

def butterFilter(samples, order = 2, cutoff = 0.005 ):
	B, A = signal.butter(order, cutoff)
 	filtered = signal.filtfilt(B,A, samples)
 	return filtered

