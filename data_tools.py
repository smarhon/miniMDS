import sys
import numpy as np
from tools import Tracker
import linear_algebra as la
import array_tools as at

class ChromParameters(object):
	"""Basic information on chromosome, inferred from input file"""
	def __init__(self, minPos, maxPos, res, name, size):
		self.minPos = minPos	#minimum genomic coordinate
		self.maxPos = maxPos	#maximum genomic coordinate
		self.res = res		#resolution (bp)
		self.name = name	#e.g. "chr22"
		self.size = size	#number of lines in file

	def getLength(self):
		"""Number of possible loci"""
		return (self.maxPos - self.minPos)/self.res + 1

	def getPointNum(self, genCoord):
		"""Converts genomic coordinate into point number"""
		if genCoord < self.minPos or genCoord > self.maxPos:
			return None
		else:
			return int((genCoord - self.minPos)/self.res) 

	def reduceRes(self, resRatio):
		"""Creates low-res version of this chromosome"""
		lowRes = self.res * resRatio
		lowMinPos = (self.minPos/lowRes)*lowRes		#approximate at low resolution
		lowMaxPos = (self.maxPos/lowRes)*lowRes
		return ChromParameters(lowMinPos, lowMaxPos, lowRes, self.name, self.size)

class Cluster(object):
	"""Intrachromosomal cluster of points or subclusters in 3-D space"""
	def __init__(self, points, clusters, chrom, offset):
		self.points = points
		self.clusters = clusters	#subclusters
		for cluster in self.clusters:	#auto-fill
			for point in cluster.points:
				self.points.append(point)	
		self.chrom = chrom	#chromosome parameters
		self.offset = offset	#indexing offset (for subclusters only)

	def getCoords(self):
		return [point.pos for point in self.getPoints()]

	def setCoords(self, coords):
		for coord, point_num in zip(coords, self.getPointNums()):
			self.points[point_num].pos = coord

	def getPointNums(self):
		return np.array([point.num for point in self.getPoints()])

	def getPoints(self):
		return self.points[np.where(self.points !=0)[0]]

	def getIndex(self, genCoord):
		"""Converts genomic coordinate into index"""
		pointNum = self.chrom.getPointNum(genCoord)
		if pointNum is None:
			return None
		else:
			pointNum -= self.offset
			if pointNum >= 0 and pointNum < len(self.points):
				point = self.points[pointNum]
				if point == 0:
					return None
				else:
					return point.index
			else:
				return None
	
	def setClusters(self, clusters):
		self.clusters = clusters
		self.points = np.zeros(max([max(cluster.getPointNums()) for cluster in clusters]) + 1, dtype=np.object)	#reset
		for cluster in self.clusters:
			for point in cluster.points:
				if point != 0:
					self.points[point.num] = point

	def createSubcluster(self, points, offset):
		"""Creates subcluster containing pointsToAdd"""
		subcluster = Cluster(points, [], self.chrom, offset)
		self.clusters.append(subcluster)

	def transform(self, r, t):
		"""Rotates by r; translates by t"""
		if r is None:	#default: no rotation
			r = np.mat(np.identity(3))
		if t is None:	#default: no translation
			t = np.mat(np.zeros(3)).T
		a = np.mat(self.getCoords())
		n = len(a)
		a_transformed = np.array(((r*a.T) + np.tile(t, (1, n))).T)
		for i, pointNum in enumerate(self.getPointNums()):
			self.points[pointNum - self.offset].pos = a_transformed[i]

	def write(self, outpath):
		with open(outpath, "w") as out:
			out.write(self.chrom.name + "\n")
			out.write(str(self.chrom.res) + "\n")
			out.write(str(self.chrom.minPos) + "\n")
			num = self.offset
			for point in self.points:
				if point == 0:
					out.write("\t".join((str(num), "nan", "nan", "nan")) + "\n")
				else:
					out.write("\t".join((str(num), str(point.pos[0]), str(point.pos[1]), str(point.pos[2]))) + "\n")
				num += 1
		out.close()

	def indexPoints(self):
		for i, point in enumerate(self.points):
			if point != 0:
				point.index = i

class Point(object):
	"""Point in 3-D space"""
	def __init__(self, pos, num, chrom, index):
		self.pos = pos	#3D coordinates
		self.num = num	#locus (not necessarily sequential)
		self.chrom = chrom	#chromosome parameters
		self.index = index	#sequential

def clusterFromBed(path, chrom, tads):
	"""Initializes cluster from intrachromosomal BED file."""
	if chrom is None:
		chrom = chromFromBed(path)

	cluster = Cluster([], [], chrom, 0)
	
	#get TAD for every locus
	if tads is None:
		tadNums = np.zeros(cluster.chrom.getLength())
	else:
		tadNums = []
		tadNum = 1
		for tad in tads:
			for i in range(tad[0], tad[1]):
				tadNums.append(tadNum)
			tadNum += 1
	maxIndex = len(tadNums) - 1

	points_to_add = np.zeros(cluster.chrom.getLength(), dtype=np.bool)	#true if locus should be added
	tracker = Tracker("Identifying loci", cluster.chrom.size)

	#find which loci should be added
	with open(path) as listFile:
		for line in listFile:
			line = line.strip().split()
			pos1 = int(line[1])
			pos2 = int(line[4])
			pointNum1 = cluster.chrom.getPointNum(pos1)
			pointNum2 = cluster.chrom.getPointNum(pos2)
			if pointNum1 is not None and pointNum2 is not None:
				tadNum1 = tadNums[min(pointNum1, maxIndex)]
				tadNum2 = tadNums[min(pointNum2, maxIndex)]
				if pointNum1 != pointNum2 and tadNum1 == tadNum2:		#must be in same TAD
					points_to_add[pointNum1] = True
					points_to_add[pointNum2] = True
			tracker.increment()
		listFile.close()

	#create points
	points = np.zeros(cluster.chrom.getLength(), dtype=np.object)
	pointNums = np.where(points_to_add == True)[0]
	for pointNum in pointNums:
		points[pointNum] = Point((0,0,0), pointNum, cluster.chrom, None)
	cluster.points = points
	cluster.indexPoints()
	
	return cluster

def chromFromBed(path):
	"""Initialize ChromParams from intrachromosomal file in BED format"""
	minPos = sys.float_info.max
	maxPos = 0
	print "Scanning {}".format(path)
	with open(path) as infile:
		for i, line in enumerate(infile):
			line = line.strip().split()
			pos1 = int(line[1])
			pos2 = int(line[4])
			if pos1 < minPos:
				minPos = pos1
			elif pos1 > maxPos:
				maxPos = pos1
			if pos2 < minPos:
				minPos = pos2
			elif pos2 > maxPos:
				maxPos = pos2
			if i == 0:
				name = line[0]
				res = (int(line[2]) - pos1)	
		infile.close()
	minPos = int(np.floor(float(minPos)/res)) * res	#round
	maxPos = int(np.ceil(float(maxPos)/res)) * res
	return ChromParameters(minPos, maxPos, res, name, i)

def basicParamsFromBed(path):
	res = None
	print "Scanning {}".format(path)
	with open(path) as infile:
		for i, line in enumerate(infile):
			if res is None:
				line = line.strip().split()
				res = (int(line[2]) - int(line[1]))
		infile.close()
	return i, res

def matFromBed(path, cluster):	
	"""Converts BED file to matrix. Only includes loci in cluster."""
	if cluster is None:
		cluster = clusterFromBed(path, None, None)

	cluster.indexPoints()
	pointNums = cluster.getPointNums()

	numpoints = len(pointNums)
	mat = np.zeros((numpoints, numpoints))	

	maxPointNum = max(pointNums)
	assert maxPointNum - cluster.offset < len(cluster.points)

	with open(path) as infile:
		for line in infile:
			line = line.strip().split()
			loc1 = int(line[1])
			loc2 = int(line[4])
			index1 = cluster.getIndex(loc1)
			index2 = cluster.getIndex(loc2)
			if index1 is not None and index2 is not None:
				if index1 > index2:
					row = index1
					col = index2
				else:
					row = index2
					col = index1
				mat[row, col] += float(line[6])
		infile.close()

	at.makeSymmetric(mat)
	rowsums = np.array([sum(row) for row in mat])
	assert len(np.where(rowsums == 0)[0]) == 0

	return mat

def highToLow(highCluster, resRatio):
	"""Reduces resolution of cluster"""
	lowChrom = highCluster.chrom.reduceRes(resRatio)

	low_n = int(np.ceil(len(highCluster.points)/float(resRatio)))

	lowCluster = Cluster(np.zeros(low_n, dtype=np.object), [], lowChrom, highCluster.offset/resRatio)

	allPointsToMerge = []
	for i in range(len(lowCluster.points)):
		allPointsToMerge.append([])
	
	for highPoint in highCluster.getPoints():
		pointsToMerge = []
		highNum = highPoint.num
		lowNum = highNum/resRatio
		allPointsToMerge[lowNum - lowCluster.offset].append(highPoint)

	index = lowCluster.offset
	for i, pointsToMerge in enumerate(allPointsToMerge):
		if len(pointsToMerge) > 0:
			lowCluster.points[i] = mergePoints(pointsToMerge, i + lowCluster.offset, lowChrom, index)
			index += 1

	return lowCluster

def mergePoints(pointsToMerge, newPointNum, chrom, index):
	"""Creates new point with average position of pointsToMerge"""
	coords = np.array([point.pos for point in pointsToMerge])
	meanCoord = np.mean(coords, axis=0)
	return Point(meanCoord, newPointNum, chrom, index)

def clusterFromFile(path):
	hasMore = True
	with open(path) as infile:
		name = infile.readline().strip()
		res = int(infile.readline().strip())
		minPos = int(infile.readline().strip())
		chrom = ChromParameters(minPos, None, res, name, None)
		cluster = Cluster([], [], chrom, 0)
		index = 0
		while hasMore:
			line = infile.readline().strip().split()
			if len(line) == 0:
				hasMore = False
			else:
				num = int(line[0])
				if line[1] == "nan":
					point = 0
				else:
					x = float(line[1])
					y = float(line[2])
					z = float(line[3])
					point = Point((x,y,z), num, chrom, index)
					index += 1
				cluster.points.append(point)
		infile.close()
	cluster.points = np.array(cluster.points)
	cluster.chrom.maxPos = cluster.chrom.minPos + cluster.chrom.res*num	#max pos is last point num
	return cluster
