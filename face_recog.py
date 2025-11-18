from __future__ import annotations
from pathlib import Path
from typing import Optional
import numpy as np
import os

# Try to import cv2 (opencv-python)
try:
	import cv2  # type: ignore
	_HAS_CV2 = True
except ImportError:
	_HAS_CV2 = False
	cv2 = None

# Try to use DeepFace if available (neural network embeddings)
try:
	from deepface import DeepFace  # type: ignore
	_HAS_DEEPFACE = True
except Exception:
	_HAS_DEEPFACE = False

DATA_DIR = Path('data')
EMB_DIR = DATA_DIR / 'embeddings'
EMB_DIR.mkdir(parents=True, exist_ok=True)


class FaceService:
	def __init__(self, supabase_client=None, emb_table: str = 'face_embeddings') -> None:
		self.has_nn = _HAS_DEEPFACE
		self.supabase = supabase_client
		self.emb_table = emb_table
		# in-memory cache: {student_id: np.ndarray}
		self._emb_cache: dict[int, np.ndarray] | None = None

	def _read_image(self, img_bgr: np.ndarray) -> np.ndarray:
		return img_bgr

	def _compute_embedding(self, img_bgr: np.ndarray) -> Optional[np.ndarray]:
		if not _HAS_CV2:
			return None
		if self.has_nn:
			try:
				# Use DeepFace to get embedding with Facenet512
				# DeepFace expects RGB
				rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
				emp = DeepFace.represent(rgb, model_name='Facenet512', enforce_detection=False)
				if isinstance(emp, list) and len(emp) > 0 and 'embedding' in emp[0]:
					return np.array(emp[0]['embedding'], dtype=np.float32)
			except Exception:
				return None
		# Fallback: simple resized grayscale vector (non-NN, placeholder)
		gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
		resized = cv2.resize(gray, (64, 64), interpolation=cv2.INTER_AREA)
		return resized.flatten().astype(np.float32) / 255.0

	def enroll_from_path(self, img_path: str, student_id: int) -> bool:
		if not _HAS_CV2 or not img_path:
			return False
		path = img_path
		if img_path.startswith('/'):
			# served path "/uploads/.." → map to filesystem
			path = os.path.join(os.getcwd(), img_path.lstrip('/'))
		img = cv2.imread(path)
		if img is None:
			return False
		e = self._compute_embedding(img)
		if e is None:
			return False

		# Save locally as fallback
		try:
			np.save(EMB_DIR / f'{student_id}.npy', e)
		except Exception:
			pass

		# Try to save embedding to Supabase table (as JSON array)
		if self.supabase is not None:
			try:
				payload = {"student_id": int(student_id), "embedding": e.tolist()}
				# use upsert to replace existing embedding
				_ = self.supabase.table(self.emb_table).upsert(payload).execute()
				# invalidate cache so new embedding is used
				self._emb_cache = None
			except Exception:
				# non-fatal
				pass

		return True

	def predict_student_id(self, frame_bgr: np.ndarray, threshold_nn: float = 0.35, threshold_fallback: float = 0.6) -> Optional[int]:
		"""Return matched student id for a frame or None when no good match.

		- For neural-network embeddings (DeepFace) we use a cosine-based distance
		  and `threshold_nn` (default 0.35).
		- For fallback non-NN embeddings we use L2 distance and `threshold_fallback`.
		"""
		e = self._compute_embedding(frame_bgr)
		if e is None:
			return None

		# Load embeddings into cache if not present
		if self._emb_cache is None:
			self._emb_cache = {}
			# Prefer Supabase table when available
			if self.supabase is not None:
				try:
					resp = self.supabase.table(self.emb_table).select("student_id, embedding").execute()
					data = getattr(resp, 'data', None) or resp
					for row in data:
						try:
							sid = int(row['student_id'])
							emb = np.array(row.get('embedding') or [], dtype=np.float32)
							if emb.size > 0:
								self._emb_cache[sid] = emb
						except Exception:
							continue
				except Exception:
					# fallback: read local files
					for emb_file in EMB_DIR.glob('*.npy'):
						try:
							self._emb_cache[int(emb_file.stem)] = np.load(emb_file)
						except Exception:
							continue
			else:
				for emb_file in EMB_DIR.glob('*.npy'):
					try:
						self._emb_cache[int(emb_file.stem)] = np.load(emb_file)
					except Exception:
						continue

		best_id = None
		best_score = float('inf')
		best_is_cosine = False

		for sid, ref in list(self._emb_cache.items()):
			try:
				if ref.shape == e.shape:
					num = float(np.dot(ref, e))
					den = float(np.linalg.norm(ref) * np.linalg.norm(e) + 1e-8)
					dist = 1.0 - (num / den)
					is_cosine = True
				else:
					dist = float(np.linalg.norm(ref - e))
					is_cosine = False
				if dist < best_score:
					best_score = dist
					best_id = int(sid)
					best_is_cosine = is_cosine
			except Exception:
				continue

		if best_id is None:
			return None

		if best_is_cosine:
			if best_score > threshold_nn:
				return None
		else:
			if best_score > threshold_fallback:
				return None

		return best_id
