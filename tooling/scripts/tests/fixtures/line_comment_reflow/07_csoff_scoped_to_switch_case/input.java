public class Demo
{
    public String classify(int code)
    {
        switch (code) {
            case 0:
                // CSOFF: LineLength
                return "case zero exceptional long output that the developer wants intact";
                // CSON: LineLength
            case 1:
                return "case one — this normal-length output should not see CSOFF";
            default:
                return "other";
        }
    }
}
