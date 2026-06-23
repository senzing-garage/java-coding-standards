public class Demo
{
    public String describe(boolean flag,
                           String userName,
                           int recordCount,
                           String detailedStatus)
    {
        return flag
            ? "userName=[ " + userName
            + " ], recordCount=[ " + recordCount
            + " ], detailedStatus=[ " + detailedStatus
            + " ]"
            : "no data";
    }
}
