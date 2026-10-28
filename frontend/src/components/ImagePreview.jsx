import React from 'react';
import { X } from 'lucide-react';

const ImagePreview = ({ imageFile, onRemove }) => {
  if (!imageFile) return null;

  const url = URL.createObjectURL(imageFile);

  return (
    <div className="image-preview-container">
      <img src={url} alt="Upload preview" className="image-preview" />
      <button className="remove-btn" onClick={onRemove} title="Remove image">
        <X size={14} color="white" />
      </button>
    </div>
  );
};

export default ImagePreview;
