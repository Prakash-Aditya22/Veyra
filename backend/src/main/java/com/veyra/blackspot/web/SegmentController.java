package com.veyra.blackspot.web;

import java.util.List;

import com.veyra.blackspot.domain.Segment;
import com.veyra.blackspot.repo.BoundingBox;
import com.veyra.blackspot.repo.SegmentRepository;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class SegmentController {

    private final SegmentRepository repo;
    private final int maxSegments;

    public SegmentController(SegmentRepository repo,
                             @Value("${blackspot.max-segments}") int maxSegments) {
        this.repo = repo;
        this.maxSegments = maxSegments;
    }

    @GetMapping("/api/segments")
    public List<Segment> segments(
            @RequestParam(required = false) String bbox,
            @RequestParam(defaultValue = "0") double minScore,
            @RequestParam(defaultValue = "6") int minCrashes,
            @RequestParam(defaultValue = "500") int limit) {

        if (limit < 1 || limit > maxSegments) {
            throw new IllegalArgumentException("limit must be between 1 and " + maxSegments);
        }
        return bbox == null
            ? repo.findTop(limit)
            : repo.findInBbox(BoundingBox.parse(bbox), minScore, minCrashes, limit);
    }

    @GetMapping("/api/segments/{segmentId}")
    public Segment segment(@PathVariable String segmentId) {
        return repo.findById(segmentId).orElseThrow(
            () -> new ApiExceptionHandler.NotFoundException("no segment " + segmentId));
    }
}
