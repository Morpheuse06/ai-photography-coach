type RatingProps = {
  value: number
}

export function Rating({ value }: RatingProps) {
  return (
    <div className="rating" aria-label={`评分 ${value} / 5`}>
      <strong>{value}</strong>
      <span>/ 5</span>
      <span className="rating-bars" aria-hidden="true">
        {[1, 2, 3, 4, 5].map((level) => (
          <i key={level} className={level <= value ? 'is-filled' : ''} />
        ))}
      </span>
    </div>
  )
}
